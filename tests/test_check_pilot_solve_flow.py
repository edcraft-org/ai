"""Model-planned equation and inequality flows, rendering and independent guards."""

from __future__ import annotations

from pathlib import Path

from test_check_pilot_application import ScriptedProvider, app, author
from test_check_pilot_catalogue import (
    EQUATION,
    INEQUALITY,
    solve_check_proposal,
    solve_plan,
    solve_template_proposal,
)

from edcraft_validator.application.check_pilot.models import (
    CoefficientDomain,
    SolveFamily,
)
from edcraft_validator.application.check_pilot.question import (
    build_solve_instance,
    guard_solve_instance,
)


def solve_provider(
    *,
    contract_id: str = EQUATION,
    relation: str = "eq",
    leading: list[int] | None = None,
) -> ScriptedProvider:
    return ScriptedProvider(
        plan=solve_plan(contract_id=contract_id, relation=relation),
        check=solve_check_proposal(),
        template=solve_template_proposal(
            contract_id=contract_id, relation=relation, leading=leading
        ),
    )


def test_equation_author_approve_generate_then_reuse_for_a_new_template(
    tmp_path: Path,
):
    application = app(tmp_path)
    provider = solve_provider()
    record = author(
        application,
        provider,
        prompt="Solve a bounded quadratic equation completely",
    )
    assert record.status == "ready"
    assert record.check is not None
    assert record.selection is not None
    assert record.selection.contract_id == EQUATION
    assert record.selection.source == "authored"
    assert record.selection.check_ref == record.check.check_ref
    assert record.check.scope["contract_id"] == EQUATION

    approved = application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    assert approved.approval == "approved"
    batch = application.generate("owner", record.template_id, seed=42, quantity=8)
    assert len(batch.questions) == 8
    assert batch.shortfall == 0
    assert any(question.answer == "No real solutions" for question in batch.questions)
    assert any("∪" in question.answer for question in batch.questions)
    for question in batch.questions:
        assert len(question.choices) == 4
        assert len(set(question.choices)) == 4
        assert question.choices[question.correct_index] == question.answer
        assert question.check_ref == record.check.check_ref
        assert any(symbol in question.question for symbol in ("=", "<", ">", "≤", "≥"))
    assert (
        application.generate("owner", record.template_id, seed=42, quantity=8) == batch
    )

    reuse_provider = solve_provider()
    reused = author(
        application,
        reuse_provider,
        prompt="Solve another bounded quadratic equation completely",
    )
    assert reused.status == "ready"
    assert reused.reused_check is True
    assert reused.check is not None
    assert reused.check.check_ref == record.check.check_ref
    assert [call["role"] for call in reuse_provider.calls] == [
        "check-planner",
        "template-author",
    ]
    assert reused.selection is not None
    assert reused.selection.source == "saved"
    assert len(application.list_checks("owner")) == 1


def test_inequality_flow_authorizes_a_separate_check_and_generates(
    tmp_path: Path,
):
    application = app(tmp_path)
    equation = author(
        application,
        solve_provider(),
        prompt="Solve a bounded quadratic equation completely",
    )
    provider = solve_provider(
        contract_id=INEQUALITY, relation="ge", leading=[-2, -1, 1, 2]
    )
    record = author(
        application,
        provider,
        prompt="Solve a bounded quadratic inequality completely",
    )
    assert record.status == "ready"
    assert record.check is not None
    assert equation.check is not None
    assert record.reused_check is False
    assert record.check.check_ref != equation.check.check_ref
    assert record.selection is not None
    assert record.selection.contract_id == INEQUALITY
    assert record.template is not None
    assert record.template["solve_family"]["relation"] == "ge"

    application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    batch = application.generate("owner", record.template_id, seed=42, quantity=10)
    assert len(batch.questions) == 10
    assert batch.shortfall == 0
    for question in batch.questions:
        assert "≥" in question.question
        assert question.choices[question.correct_index] == question.answer
    assert any(question.answer == "All real numbers" for question in batch.questions)
    assert any("∪" in question.answer for question in batch.questions)


def test_negative_leading_repeated_root_sets_render_with_the_correct_sign():
    family = SolveFamily(
        relation="lt",
        degree=2,
        coefficients=[
            CoefficientDomain(exponent=0, values=[-1, 0, 1]),
            CoefficientDomain(exponent=1, values=[-1, 0, 1]),
            CoefficientDomain(exponent=2, values=[-1]),
        ],
    )
    strict = build_solve_instance(family, (0, 0, -1), seed=1)
    assert strict.answer == "(-∞, 0) ∪ (0, ∞)"
    assert guard_solve_instance(strict, num_distractors=3) == []

    inclusive = build_solve_instance(
        family.model_copy(update={"relation": "le"}), (0, 0, -1), seed=1
    )
    assert inclusive.answer == "All real numbers"
    assert guard_solve_instance(inclusive, num_distractors=3) == []

    point = build_solve_instance(
        family.model_copy(update={"relation": "ge"}), (0, 0, -1), seed=1
    )
    assert point.answer == "{0}"
    assert guard_solve_instance(point, num_distractors=3) == []


def test_template_relation_mismatch_keeps_the_check_and_blocks_the_template(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        plan=solve_plan(contract_id=EQUATION, relation="eq"),
        check=solve_check_proposal(),
        template=solve_template_proposal(
            contract_id=EQUATION, relation="lt", leading=[1, 2, 3]
        ),
    )
    application = app(tmp_path)
    record = author(application, provider, prompt="Solve an equation")
    assert record.status == "needs_review"
    assert record.check is not None
    assert record.template is None
    assert any(
        "template relation does not match the selected plan" in finding
        for finding in record.findings
    )
    assert record.selection is not None
    assert record.selection.contract_id == EQUATION
    assert len(application.list_checks("owner")) == 1
