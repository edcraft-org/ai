"""Math plugin for the domain-neutral NL-fidelity gate.

The plugin owns three things the engine must not: the blind parse-back prompt,
deterministic anchor rules, and a conservative IR equivalence check. A parse
that cannot be compared is ``inconclusive``; it is never silently approved.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sympy
from pydantic import BaseModel

from edcraft_validator.application.fidelity.contracts import (
    CanonicalArtifact,
    EvidenceStrength,
    FidelityStatus,
    FidelityVerdict,
)
from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
    compile_relation,
)
from edcraft_validator.domains.math.ir.schema import (
    Expr,
    Given,
    MathItemSpec,
    MathReconstruction,
)
from edcraft_validator.domains.math.ir.solve import goal_symbols
from edcraft_validator.domains.math.validation.primitives import expression_equiv
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

PROMPT_VERSION = "math-fidelity/1"
SCHEMA_NAME = "math_reconstruction"

_SYSTEM_PROMPT = """\
You are a blind parser for a math problem. Restate the problem exactly as the
supplied typed IR. You have not seen the source item, its answer, its distractors
or its topic; do not try to infer them.

Rules:
- Do not solve the problem and do not add an answer.
- Parse only what the text states. Do not invent quantities, constraints or
  variables.
- Use exact decimal or rational strings for every number. Never emit floats.
- Use only the closed vocabulary in the response schema: relation kinds
  eq/ne/lt/le/gt/ge; goal kinds evaluate/solve/simplify/factor/expand/derivative/
  integral/limit/determinant/eigenvalues; operators add/sub/mul/div/pow/sqrt/abs/
  exp/sin/cos/tan/asin/acos/atan/log.
- Declare every variable in symbols and reference only those names.
- If the text supports more than one reading, set ambiguous=true and give at
  least one concrete ambiguity. Do not guess a single reading.
"""

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_NUMERIC_LITERAL = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


class MathFidelityPlugin:
    """Blind parse-back and IR comparison for the math domain."""

    domain: str = "math"
    artifact_model: type[BaseModel] = MathItemSpec
    evidence_strength: EvidenceStrength = "probabilistic"

    def requires_check(self, artifact: BaseModel) -> bool:
        return _item(artifact).text.mode == "prose"

    def reconstruction_request(self, text: str) -> StructuredGenerationRequest[Any]:
        return StructuredGenerationRequest(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_model=MathReconstruction,
            schema_name=SCHEMA_NAME,
            prompt_version=PROMPT_VERSION,
        )

    def canonicalize(self, artifact: BaseModel) -> CanonicalArtifact:
        item = _item(artifact)
        payload = _canonical_payload(item)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return CanonicalArtifact(
            domain=self.domain,
            payload=payload,
            digest=hashlib.sha256(encoded.encode()).hexdigest(),
        )

    def check_anchors(self, artifact: BaseModel, text: str) -> FidelityVerdict:
        item = _item(artifact)
        spec = item.text
        template = spec.template
        anchors = spec.anchors
        reasons: list[str] = []
        spans: dict[str, tuple[int, int]] = {}

        for name, span in anchors.items():
            if name not in template:
                reasons.append(f"anchor {name!r} does not appear in the template")
            bounds = _span_bounds(span)
            if bounds is None or not (0 <= bounds[0] < bounds[1] <= len(template)):
                reasons.append(
                    f"anchor {name!r} has an invalid span {span!r} for a "
                    f"template of length {len(template)}"
                )
                continue
            spans[name] = bounds

        ordered = sorted(spans.items(), key=lambda entry: entry[1])
        previous_end = -1
        previous_name: str | None = None
        for name, (start, end) in ordered:
            if start < previous_end:
                reasons.append(f"anchor {name!r} overlaps anchor {previous_name!r}")
            previous_end = max(previous_end, end)
            previous_name = name

        literals = _numeric_literals(template)
        if literals and not anchors:
            reasons.append("template contains numeric literals but declares no anchors")
        elif literals:
            for literal, start, end in literals:
                if not any(
                    anchor_start <= start and end <= anchor_end
                    for anchor_start, anchor_end in spans.values()
                ):
                    reasons.append(
                        f"numeric literal {literal!r} at [{start}, {end}) is not "
                        "covered by an anchor"
                    )

        evidence = {
            "mode": spec.mode,
            "anchor_count": len(anchors),
            "numeric_literal_count": len(literals),
            "numeric_literals": [literal for literal, _, _ in literals],
        }
        if reasons:
            return FidelityVerdict(status="failed", reasons=reasons, evidence=evidence)
        return FidelityVerdict(status="passed", evidence=evidence)

    def equivalent(
        self, expected: BaseModel, reconstructed: BaseModel
    ) -> FidelityVerdict:
        item = _item(expected)
        parse = _reconstruction(reconstructed)

        if parse.ambiguous:
            return FidelityVerdict(
                status="inconclusive",
                reasons=list(parse.ambiguities),
                evidence={"ambiguous": True, "ambiguities": parse.ambiguities},
            )

        expected_symbols = {symbol.name: symbol.domain for symbol in item.symbols}
        reconstructed_symbols = {symbol.name: symbol.domain for symbol in parse.symbols}
        expected_goal_symbols = tuple(sorted(goal_symbols(item.goal)))
        reconstructed_goal_symbols = tuple(sorted(goal_symbols(parse.goal)))
        evidence: dict[str, Any] = {
            "expected_symbols": sorted(expected_symbols),
            "reconstructed_symbols": sorted(reconstructed_symbols),
            "expected_goal": {
                "kind": item.goal.kind,
                "symbols": list(expected_goal_symbols),
            },
            "reconstructed_goal": {
                "kind": parse.goal.kind,
                "symbols": list(reconstructed_goal_symbols),
            },
            "expected_given_count": len(item.givens),
            "reconstructed_given_count": len(parse.givens),
        }

        missing = sorted(set(expected_symbols) - set(reconstructed_symbols))
        extra = sorted(set(reconstructed_symbols) - set(expected_symbols))
        domain_mismatches = sorted(
            name
            for name in set(expected_symbols) & set(reconstructed_symbols)
            if expected_symbols[name] != reconstructed_symbols[name]
        )
        reasons: list[str] = []
        if missing:
            reasons.append(f"missing symbols: {', '.join(missing)}")
        if extra:
            reasons.append(f"extra symbols: {', '.join(extra)}")
        for name in domain_mismatches:
            reasons.append(
                f"symbol {name!r} domain is {expected_symbols[name]!r}, "
                f"not {reconstructed_symbols[name]!r}"
            )
        if reasons:
            return FidelityVerdict(status="failed", reasons=reasons, evidence=evidence)

        if item.goal.kind != parse.goal.kind:
            return FidelityVerdict(
                status="failed",
                reasons=[f"goal kind is {item.goal.kind!r}, not {parse.goal.kind!r}"],
                evidence=evidence,
            )
        if expected_goal_symbols != reconstructed_goal_symbols:
            return FidelityVerdict(
                status="failed",
                reasons=[
                    "goal symbols are "
                    f"{list(reconstructed_goal_symbols)!r}, not "
                    f"{list(expected_goal_symbols)!r}"
                ],
                evidence=evidence,
            )

        goal_status, goal_reasons = _compare_goals(item, parse)
        evidence["goal_comparison"] = {
            "status": goal_status,
            "reasons": goal_reasons,
        }
        if goal_status != "passed":
            return FidelityVerdict(
                status=goal_status,
                reasons=goal_reasons,
                evidence=evidence,
            )
        try:
            comparison, leftover_expected, leftover_reconstructed = _compare_givens(
                item, parse
            )
        except Exception as exc:  # noqa: BLE001 - comparison failure is not approval
            return FidelityVerdict(
                status="inconclusive",
                reasons=[f"givens could not be compared: {exc}"],
                evidence=evidence,
            )

        evidence.update(comparison)
        if leftover_expected or leftover_reconstructed:
            if leftover_expected:
                reasons.append(
                    "missing givens: "
                    + ", ".join(given.label for given in leftover_expected)
                )
            if leftover_reconstructed:
                reasons.append(
                    "extra givens: "
                    + ", ".join(given.label for given in leftover_reconstructed)
                )
            return FidelityVerdict(status="failed", reasons=reasons, evidence=evidence)

        return FidelityVerdict(
            status="passed",
            reasons=["symbols, goal and givens agree with the blind parse"],
            evidence=evidence,
        )


PLUGIN = MathFidelityPlugin()


def math_fidelity_plugin() -> MathFidelityPlugin:
    """Return the stateless math plugin used by application wiring."""
    return PLUGIN


@dataclass(frozen=True)
class _ComparableGiven:
    kind: str
    label: str
    residual: Any = None
    text: str = ""


def _item(artifact: BaseModel) -> MathItemSpec:
    if not isinstance(artifact, MathItemSpec):
        raise TypeError("math fidelity expects a MathItemSpec")
    return artifact


def _reconstruction(artifact: BaseModel) -> MathReconstruction:
    if not isinstance(artifact, MathReconstruction):
        raise TypeError("math fidelity expects a MathReconstruction")
    return artifact


def _compare_goals(
    expected: MathItemSpec, reconstructed: MathReconstruction
) -> tuple[FidelityStatus, list[str]]:
    """Compare the whole goal payload, not just its kind and symbols.

    Two questions can share a goal kind while asking for different expressions,
    points or matrices. Those differences are mismatches, not a pass.
    """
    symbols = build_symbols(expected.symbols)
    left_goal = expected.goal
    right_goal = reconstructed.goal
    reasons: list[str] = []
    if left_goal.order != right_goal.order:
        reasons.append(f"goal order is {right_goal.order}, not {left_goal.order}")
    if left_goal.domain != right_goal.domain:
        reasons.append(
            f"goal domain is {right_goal.domain!r}, not {left_goal.domain!r}"
        )

    try:
        expression_status, expression_reason = _compare_optional_expressions(
            left_goal.expr, right_goal.expr, symbols, label="expression"
        )
        if expression_status == "failed":
            reasons.append("goal expressions differ")
        elif expression_status == "inconclusive":
            return "inconclusive", [expression_reason]

        point_status, point_reason = _compare_optional_expressions(
            left_goal.point, right_goal.point, symbols, label="evaluation point"
        )
        if point_status == "failed":
            reasons.append("goal evaluation points differ")
        elif point_status == "inconclusive":
            return "inconclusive", [point_reason]

        matrix_status, matrix_reason = _compare_optional_matrices(
            left_goal.matrix, right_goal.matrix, symbols
        )
        if matrix_status == "failed":
            reasons.extend(matrix_reason)
        elif matrix_status == "inconclusive":
            return "inconclusive", matrix_reason
    except MathCompileError as exc:
        return "inconclusive", [f"goal payload could not be compiled: {exc}"]

    if reasons:
        return "failed", reasons
    return "passed", []


def _compare_optional_expressions(
    expected: Expr | None,
    reconstructed: Expr | None,
    symbols: Mapping[str, sympy.Symbol],
    *,
    label: str,
) -> tuple[FidelityStatus, str]:
    if expected is None and reconstructed is None:
        return "passed", ""
    if expected is None or reconstructed is None:
        return "failed", f"goal {label} is missing on one side"
    equivalence = _expressions_equivalent(
        compile_expr(expected, symbols), compile_expr(reconstructed, symbols)
    )
    if equivalence is None:
        return "inconclusive", f"goal {label} could not be compared"
    if equivalence:
        return "passed", ""
    return "failed", f"goal {label} differs"


def _compare_optional_matrices(
    expected: list[list[Expr]] | None,
    reconstructed: list[list[Expr]] | None,
    symbols: Mapping[str, sympy.Symbol],
) -> tuple[FidelityStatus, list[str]]:
    if expected is None and reconstructed is None:
        return "passed", []
    if expected is None or reconstructed is None:
        return "failed", ["goal matrix is missing on one side"]
    if len(expected) != len(reconstructed) or any(
        len(row) != len(other)
        for row, other in zip(expected, reconstructed, strict=False)
    ):
        return "failed", ["goal matrix shapes differ"]
    reasons: list[str] = []
    for row_index, (row, other_row) in enumerate(
        zip(expected, reconstructed, strict=True)
    ):
        for column_index, (cell, other_cell) in enumerate(
            zip(row, other_row, strict=True)
        ):
            equivalence = _expressions_equivalent(
                compile_expr(cell, symbols), compile_expr(other_cell, symbols)
            )
            if equivalence is None:
                return "inconclusive", [
                    f"goal matrix entry {row_index},{column_index} "
                    "could not be compared"
                ]
            if not equivalence:
                reasons.append(f"goal matrix entry {row_index},{column_index} differs")
    if reasons:
        return "failed", reasons
    return "passed", []


def _expressions_equivalent(left: sympy.Expr, right: sympy.Expr) -> bool | None:
    """Decide semantic equality; ``None`` means the comparison could not decide."""
    result = expression_equiv(left, right)
    if result.status == "passed":
        return True
    if result.status == "failed":
        return False
    return None


def _canonical_payload(item: MathItemSpec) -> dict[str, Any]:
    symbols = sorted(
        (symbol.model_dump(mode="json") for symbol in item.symbols),
        key=lambda symbol: symbol["name"],
    )
    givens = sorted(
        (_canonical_given(given) for given in item.givens),
        key=_json_key,
    )
    goal = item.goal.model_dump(mode="json")
    goal["symbols"] = list(sorted(goal_symbols(item.goal)))
    goal.pop("symbol", None)
    text = {
        "mode": item.text.mode,
        "template": item.text.template,
        "anchors": {
            name: list(span) for name, span in sorted(item.text.anchors.items())
        },
    }
    return {
        "schema_version": item.schema_version,
        "topic": item.topic,
        "symbols": symbols,
        "givens": givens,
        "goal": goal,
        "text": text,
    }


def _canonical_given(given: Given) -> dict[str, Any]:
    if given.kind == "relation" and given.relation is not None:
        return {
            "kind": "relation",
            "relation": given.relation.model_dump(mode="json"),
        }
    if given.kind == "domain":
        return {
            "kind": "domain",
            "symbol": given.symbol,
            "domain": given.domain,
        }
    return {"kind": "dataset", "values": sorted(given.values)}


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _span_bounds(span: object) -> tuple[int, int] | None:
    if not isinstance(span, (tuple, list)) or len(span) != 2:
        return None
    start, end = span
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    return start, end


def _numeric_literals(template: str) -> list[tuple[str, int, int]]:
    placeholders = [
        (match.start(), match.end()) for match in _PLACEHOLDER.finditer(template)
    ]
    literals: list[tuple[str, int, int]] = []
    for match in _NUMERIC_LITERAL.finditer(template):
        if any(start <= match.start() < end for start, end in placeholders):
            continue
        literals.append((match.group(0), match.start(), match.end()))
    return literals


def _compare_givens(
    expected: MathItemSpec, reconstructed: MathReconstruction
) -> tuple[dict[str, Any], list[_ComparableGiven], list[_ComparableGiven]]:
    symbols = build_symbols(expected.symbols)
    expected_givens = _comparable_givens(expected.givens, symbols)
    reconstructed_givens = _comparable_givens(reconstructed.givens, symbols)
    matched_expected = [False] * len(expected_givens)
    matched_reconstructed = [False] * len(reconstructed_givens)
    for expected_index, expected_given in enumerate(expected_givens):
        for reconstructed_index, reconstructed_given in enumerate(reconstructed_givens):
            if matched_reconstructed[reconstructed_index]:
                continue
            if _givens_equivalent(expected_given, reconstructed_given):
                matched_expected[expected_index] = True
                matched_reconstructed[reconstructed_index] = True
                break
    leftover_expected = [
        given
        for index, given in enumerate(expected_givens)
        if not matched_expected[index]
    ]
    leftover_reconstructed = [
        given
        for index, given in enumerate(reconstructed_givens)
        if not matched_reconstructed[index]
    ]
    return (
        {
            "expected_givens": [given.label for given in expected_givens],
            "reconstructed_givens": [given.label for given in reconstructed_givens],
            "unmatched_expected_givens": [given.label for given in leftover_expected],
            "unmatched_reconstructed_givens": [
                given.label for given in leftover_reconstructed
            ],
        },
        leftover_expected,
        leftover_reconstructed,
    )


def _comparable_givens(
    givens: list[Given], symbols: Mapping[str, sympy.Symbol]
) -> list[_ComparableGiven]:
    comparable: list[_ComparableGiven] = []
    for given in givens:
        if given.kind == "relation" and given.relation is not None:
            relation = compile_relation(given.relation, symbols)
            label = _relation_label(given.relation)
            residual = sympy.simplify(relation.lhs - relation.rhs)
            comparable.append(
                _ComparableGiven(
                    kind=f"relation_{given.relation.kind}",
                    label=label,
                    residual=residual,
                )
            )
        elif given.kind == "domain":
            comparable.append(
                _ComparableGiven(
                    kind="domain",
                    label=f"{given.symbol} in {given.domain}",
                    text=_json_key(_canonical_given(given)),
                )
            )
        else:
            values = ",".join(sorted(given.values))
            comparable.append(
                _ComparableGiven(
                    kind="dataset",
                    label=f"dataset({values})",
                    text=_json_key(_canonical_given(given)),
                )
            )
    return comparable


_MIRRORED_RELATIONS = frozenset(
    {
        ("relation_lt", "relation_gt"),
        ("relation_le", "relation_ge"),
    }
)


def _givens_equivalent(left: _ComparableGiven, right: _ComparableGiven) -> bool:
    if left.kind == right.kind:
        if left.kind in {"relation_eq", "relation_ne"}:
            # Equalities and inequalities are symmetric under operand swap.
            return _residual_zero(left.residual, right.residual, flipped=False) or (
                _residual_zero(left.residual, right.residual, flipped=True)
            )
        if left.kind.startswith("relation_"):
            # Two same-direction inequalities are equivalent only when their
            # residuals agree; multiplying by -1 reverses the direction.
            return _residual_zero(left.residual, right.residual, flipped=False)
        return left.text == right.text
    if (left.kind, right.kind) in _MIRRORED_RELATIONS:
        # ``x < 5`` and ``5 > x`` describe the same half-line.
        return _residual_zero(left.residual, right.residual, flipped=True)
    return False


def _residual_zero(left: Any, right: Any, *, flipped: bool) -> bool:
    if left is None or right is None:
        return False
    difference = (
        sympy.simplify(left + right) if flipped else sympy.simplify(left - right)
    )
    return bool(difference == 0)


def _relation_label(relation: Any) -> str:
    operators = {
        "eq": "=",
        "ne": "!=",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
    }
    return (
        f"{_expr_label(relation.lhs)} {operators[relation.kind]} "
        f"{_expr_label(relation.rhs)}"
    )


def _expr_label(expr: Expr) -> str:
    if expr.num is not None:
        return expr.num
    if expr.sym is not None:
        return expr.sym
    if expr.param is not None:
        return expr.param
    if expr.op is not None:
        return f"{expr.op}({', '.join(_expr_label(arg) for arg in expr.args)})"
    raise ValueError("expression node has no payload")
