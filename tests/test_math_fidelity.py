"""NL-fidelity engine and math plugin behavior, using a scripted provider."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from edcraft_validator.application.fidelity.contracts import FidelityVerdict
from edcraft_validator.application.fidelity.engine import (
    FidelityCache,
    default_cache,
    verify_text_fidelity,
)
from edcraft_validator.domains.math.fidelity import (
    PROMPT_VERSION,
    math_fidelity_plugin,
)
from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathReconstruction,
    PrimitiveSpec,
    Relation,
    SymbolSpec,
    TextMode,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.math_tools import (
    MathFidelityRequest,
    verify_text_fidelity_tool,
)

PLUGIN = math_fidelity_plugin()
TEXT = "A number multiplied by 2 is 6."


class FakeFidelityProvider:
    provider = "scripted"
    model = "blind-parser"

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls = 0

    def generation_settings(self) -> dict[str, Any]:
        return {"mode": "scripted"}

    def generate(self, request: StructuredGenerationRequest[Any]) -> Any:
        self.calls += 1
        self.last_usage = TokenUsage(input_tokens=11, output_tokens=3)
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, BaseModel):
            return request.response_model.model_validate(self.response.model_dump())
        return self.response


def _item(
    *,
    mode: TextMode = "prose",
    template: str = TEXT,
    anchors: dict[str, tuple[int, int]] | None = None,
    relation: Relation | None = None,
) -> MathItemSpec:
    if anchors is None:
        anchors = {"number": (0, len(template))}
    return MathItemSpec(
        topic="linear equations",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[
            Given(
                id="g1",
                kind="relation",
                relation=relation or _two_x_equals_six(),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        text=TextSpec(mode=mode, template=template, anchors=anchors),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )


def _reconstruction(
    *,
    lhs: Expr | None = None,
    rhs: Expr | None = None,
    ambiguous: bool = False,
    ambiguities: list[str] | None = None,
) -> MathReconstruction:
    return MathReconstruction(
        topic="linear equations",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[
            Given(
                id="g1",
                kind="relation",
                relation=Relation(
                    kind="eq",
                    lhs=lhs or _two_x(),
                    rhs=rhs or _six(),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        ambiguous=ambiguous,
        ambiguities=ambiguities or [],
    )


def _two_x() -> Expr:
    return Expr(op="mul", args=[Expr(num="2"), Expr(sym="x")])


def _six() -> Expr:
    return Expr(num="6")


def _two_x_equals_six() -> Relation:
    return Relation(kind="eq", lhs=_two_x(), rhs=_six())


async def _verify(
    item: MathItemSpec,
    response: Any,
    *,
    cache: FidelityCache | None = None,
) -> tuple[Any, FakeFidelityProvider]:
    fake = FakeFidelityProvider(response)
    report = await verify_text_fidelity(
        PLUGIN,
        item,
        item.text.template,
        provider_factory=lambda: fake,
        cache=cache if cache is not None else FidelityCache(),
    )
    return report, fake


async def test_symbolic_item_skips_the_model() -> None:
    report, fake = await _verify(_item(mode="symbolic"), _reconstruction())
    assert report.status == "passed"
    assert report.cached is False
    assert report.reconstruction is None
    assert fake.calls == 0
    assert report.prompt_version == PROMPT_VERSION
    assert "constrained realization" in report.verdict.reasons[0]


async def test_prose_with_matching_reconstruction_passes() -> None:
    report, fake = await _verify(_item(), _reconstruction())
    assert report.status == "passed"
    assert report.cached is False
    assert fake.calls == 1
    assert report.provider == "scripted"
    assert report.model == "blind-parser"
    assert report.usage.model_call_count == 1
    assert report.reconstruction is not None
    assert report.error_code is None


async def test_mcp_tool_maps_fidelity_outcomes() -> None:
    default_cache().clear()
    passed = await verify_text_fidelity_tool(
        MathFidelityRequest(item=_item(), timeout_seconds=10),
        provider_factory=lambda: FakeFidelityProvider(_reconstruction()),
        timeout_seconds=10,
    )
    assert passed.status == "passed"
    assert passed.details["routes_to_review"] is False

    wrong = Expr(op="mul", args=[Expr(num="3"), Expr(sym="x")])
    failed = await verify_text_fidelity_tool(
        MathFidelityRequest(
            item=_item(),
            text="A number multiplied by 3 is 6.",
            timeout_seconds=10,
        ),
        provider_factory=lambda: FakeFidelityProvider(_reconstruction(lhs=wrong)),
        timeout_seconds=10,
    )
    assert failed.status == "failed"
    assert failed.findings[0].code == "FIDELITY_MISMATCH"
    assert failed.details["routes_to_review"] is True


async def test_mismatched_equation_fails() -> None:
    wrong = Expr(op="mul", args=[Expr(num="3"), Expr(sym="x")])
    report, fake = await _verify(_item(), _reconstruction(lhs=wrong))
    assert report.status == "failed"
    assert fake.calls == 1
    assert any(
        "missing givens" in reason or "extra givens" in reason
        for reason in report.verdict.reasons
    )
    assert report.verdict.evidence["unmatched_expected_givens"]


async def test_ambiguous_reconstruction_is_inconclusive() -> None:
    reason = "The 6 could be the result or a coefficient."
    report, fake = await _verify(
        _item(),
        _reconstruction(ambiguous=True, ambiguities=[reason]),
    )
    assert report.status == "inconclusive"
    assert fake.calls == 1
    assert report.verdict.reasons == [reason]
    assert report.verdict.evidence["ambiguous"] is True


async def test_anchor_failure_skips_the_model() -> None:
    item = _item(anchors={})
    report, fake = await _verify(item, _reconstruction())
    assert report.status == "failed"
    assert fake.calls == 0
    assert any("declares no anchors" in reason for reason in report.verdict.reasons)


async def test_uncovered_numeric_literal_fails_before_the_model() -> None:
    item = _item(anchors={"number": (0, 8)})
    report, fake = await _verify(item, _reconstruction())
    assert report.status == "failed"
    assert fake.calls == 0
    assert any(
        "not covered by an anchor" in reason for reason in report.verdict.reasons
    )


async def test_judge_invalid_response_is_inconclusive() -> None:
    report, fake = await _verify(_item(), object())
    assert report.status == "inconclusive"
    assert fake.calls == 1
    assert report.error_code == "JUDGE_INVALID_RESPONSE"
    assert report.status != "passed"


async def test_cache_hit_avoids_a_second_model_call_and_rechecks() -> None:
    cache = FidelityCache()
    first, fake = await _verify(_item(), _reconstruction(), cache=cache)
    second, _ = await _verify(_item(), _reconstruction(), cache=cache)
    assert first.cached is False
    assert second.cached is True
    assert second.status == "passed"
    assert fake.calls == 1


async def test_cache_key_includes_the_expected_artifact() -> None:
    cache = FidelityCache()
    _, fake = await _verify(_item(), _reconstruction(), cache=cache)
    changed = _item(relation=Relation(kind="eq", lhs=_two_x(), rhs=Expr(num="7")))
    second, second_fake = await _verify(changed, _reconstruction(), cache=cache)
    assert second.cached is False
    assert second.status == "failed"
    assert fake.calls + second_fake.calls == 2


def test_default_cache_is_bounded_and_exposed() -> None:
    cache = default_cache()
    assert isinstance(cache, FidelityCache)
    assert cache.max_entries == 256


def test_cache_evicts_the_least_recently_used_entry() -> None:
    cache = FidelityCache(max_entries=2)
    first, second, third = (
        _reconstruction(),
        _reconstruction(),
        _reconstruction(),
    )
    cache.put("first", first)
    cache.put("second", second)
    assert cache.get("first") is first
    cache.put("third", third)
    assert cache.get("second") is None
    assert cache.get("first") is first
    assert cache.get("third") is third


def test_anchor_coverage_accepts_numeric_literals() -> None:
    item = _item()
    verdict = PLUGIN.check_anchors(item, item.text.template)
    assert verdict.status == "passed"
    assert verdict.evidence["numeric_literal_count"] == 2


def test_anchor_rules_reject_overlapping_spans() -> None:
    item = _item(
        template="2 plus 2 equals 4",
        anchors={"plus": (0, 6), "equals": (4, 10)},
    )
    verdict = PLUGIN.check_anchors(item, item.text.template)
    assert verdict.status == "failed"
    assert any("overlaps" in reason for reason in verdict.reasons)


def test_anchor_name_must_appear_in_the_template() -> None:
    item = _item(template="2 plus 2", anchors={"missing": (0, 8)})
    verdict = PLUGIN.check_anchors(item, item.text.template)
    assert verdict.status == "failed"
    assert any("does not appear" in reason for reason in verdict.reasons)


def test_symbolic_placeholders_may_skip_anchors() -> None:
    item = _item(mode="symbolic", template="{a}x + {b} = {c}", anchors={})
    verdict = PLUGIN.check_anchors(item, item.text.template)
    assert verdict.status == "passed"
    assert verdict.evidence["numeric_literal_count"] == 0


def test_anchor_span_must_fit_the_template() -> None:
    item = _item(template="2 + 2", anchors={"2": (0, 99)})
    verdict = PLUGIN.check_anchors(item, item.text.template)
    assert verdict.status == "failed"
    assert any("invalid span" in reason for reason in verdict.reasons)


def test_canonicalize_excludes_answer_distractors_and_validation() -> None:
    item = _item()
    enriched = item.model_copy(
        update={
            "answer": Answer(kind="numeric", items=["3"], display="3"),
            "distractors": [
                Distractor(
                    value=Expr(num="4"),
                    misconception="arithmetic slip",
                )
            ],
            "validation": ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
        }
    )
    assert PLUGIN.canonicalize(item).digest == PLUGIN.canonicalize(enriched).digest


def test_math_plugin_is_domain_neutral_wrapper() -> None:
    assert PLUGIN.domain == "math"
    assert PLUGIN.artifact_model is MathItemSpec
    assert PLUGIN.evidence_strength == "probabilistic"


def test_symbol_and_goal_mismatch_is_failed() -> None:
    item = _item()
    parse = _reconstruction().model_copy(
        update={
            "symbols": [SymbolSpec(name="y", domain="real")],
            "goal": Goal(kind="solve", symbol="y"),
        }
    )
    verdict: FidelityVerdict = PLUGIN.equivalent(item, parse)
    assert verdict.status == "failed"
    assert any("missing symbols" in reason for reason in verdict.reasons)


def test_domain_mismatch_is_failed() -> None:
    item = _item()
    parse = _reconstruction().model_copy(
        update={"symbols": [SymbolSpec(name="x", domain="integer")]}
    )
    verdict = PLUGIN.equivalent(item, parse)
    assert verdict.status == "failed"
    assert any("domain" in reason for reason in verdict.reasons)


def test_equivalent_relations_allow_swapped_sides() -> None:
    item = _item()
    swapped = _reconstruction(
        lhs=_six(),
        rhs=_two_x(),
    )
    verdict = PLUGIN.equivalent(item, swapped)
    assert verdict.status == "passed"


def test_extra_given_is_failed() -> None:
    item = _item()
    parse = _reconstruction()
    parse = parse.model_copy(
        update={
            "givens": [
                *parse.givens,
                Given(
                    id="g2",
                    kind="relation",
                    relation=Relation(kind="eq", lhs=Expr(sym="x"), rhs=_six()),
                ),
            ]
        }
    )
    verdict = PLUGIN.equivalent(item, parse)
    assert verdict.status == "failed"
    assert any("extra givens" in reason for reason in verdict.reasons)


def test_incomparable_parse_is_inconclusive() -> None:
    item = _item()
    parse = _reconstruction(lhs=Expr(op="not_an_operator", args=[Expr(sym="x")]))
    # The closed schema permits any op string; the compiler rejects it.
    verdict = PLUGIN.equivalent(item, parse)
    assert verdict.status == "inconclusive"
    assert verdict.status != "passed"
