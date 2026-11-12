"""Regressions for kernel dimension, scope and sampling enforcement."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from edcraft_validator.application.check_pilot import structured
from edcraft_validator.application.check_pilot.contracts import (
    _kernel_scope_findings,
    applicability_findings,
    plan_covers_template_findings,
    scope_applicability_findings,
)
from edcraft_validator.application.check_pilot.kernel_registry import (
    kernel_contract,
    kernel_expected_answer,
    kernel_render_answer,
)
from edcraft_validator.application.check_pilot.models import (
    KernelGoal,
    NumericBinding,
    StructuredProblemFamily,
)
from edcraft_validator.application.check_pilot.structured import (
    boundary_assignments,
    problem_goal_findings,
    sampled_assignments,
    structured_family_goal,
)

DETERMINANT = "matrix.determinant/1"
ANTIDERIVATIVE = "polynomial.antiderivative/1"


def determinant_problem() -> dict:
    return {"kind": "matrix_determinant", "matrix": [["1", "2"], ["3", "4"]]}


def determinant_family() -> StructuredProblemFamily:
    return StructuredProblemFamily(
        contract_id=DETERMINANT,
        problem=determinant_problem(),
        bindings=[
            NumericBinding(path="matrix.0.0", values=[1, 2, 3]),
            NumericBinding(path="matrix.1.1", values=[4, 5, 6]),
        ],
    )


def antiderivative_goal(*, general: bool) -> KernelGoal:
    contract = kernel_contract(ANTIDERIVATIVE)
    assert contract is not None
    return KernelGoal(
        operation=contract.operation,
        answer_type=contract.answer_type,
        min_degree=contract.min_degree,
        max_degree=contract.max_degree,
        max_abs_coefficient=contract.max_abs_coefficient,
        min_dimension=contract.min_dimension,
        max_dimension=contract.max_dimension,
        requires_general_antiderivative=general,
        domain_assumptions=list(contract.domain_assumptions),
    )


def test_kernel_goal_validates_ordered_dimension_bounds():
    with pytest.raises(ValidationError):
        KernelGoal(
            operation="matrix-determinant",
            answer_type="scalar",
            max_degree=0,
            max_abs_coefficient=10,
            min_dimension=3,
            max_dimension=2,
        )


def test_family_goal_carries_the_exact_minimum_dimension():
    goal = structured_family_goal(determinant_family())

    assert goal.min_dimension == goal.max_dimension == 2


def test_plan_with_a_higher_minimum_dimension_rejects_a_2x2_family():
    actual = structured_family_goal(determinant_family())
    plan = actual.model_copy(update={"min_dimension": 3, "max_dimension": 3})

    findings = plan_covers_template_findings(plan, actual)

    assert any("below the selected plan" in finding for finding in findings)


def test_exact_2x2_plan_accepts_a_2x2_family():
    actual = structured_family_goal(determinant_family())
    plan = actual.model_copy(update={"min_dimension": 2, "max_dimension": 2})

    assert plan_covers_template_findings(plan, actual) == []


def test_range_plan_still_accepts_a_2x2_family():
    actual = structured_family_goal(determinant_family())
    plan = actual.model_copy(update={"min_dimension": 2, "max_dimension": 3})

    assert plan_covers_template_findings(plan, actual) == []


def test_kernel_goal_rejects_a_minimum_dimension_below_the_contract():
    contract = kernel_contract(DETERMINANT)
    assert contract is not None
    goal = structured_family_goal(determinant_family()).model_copy(
        update={"min_dimension": 0}
    )

    assert "requested minimum dimension is below the contract" in (
        applicability_findings(contract, goal)
    )


def test_kernel_goal_rejects_inverted_dimension_bounds():
    contract = kernel_contract(DETERMINANT)
    assert contract is not None
    goal = structured_family_goal(determinant_family()).model_copy(
        update={"min_dimension": 3, "max_dimension": 2}
    )

    assert "requested minimum dimension exceeds its maximum" in (
        applicability_findings(contract, goal)
    )


def test_problem_goal_findings_uses_the_requested_minimum_dimension():
    goal = structured_family_goal(determinant_family())
    exact_three = goal.model_copy(update={"min_dimension": 3, "max_dimension": 3})

    assert problem_goal_findings(DETERMINANT, goal, determinant_problem()) == []
    findings = problem_goal_findings(DETERMINANT, exact_three, determinant_problem())
    assert any("dimension is below" in finding for finding in findings)


def test_general_answer_goal_is_not_covered_by_a_primitive_scope():
    contract = kernel_contract(ANTIDERIVATIVE)
    assert contract is not None
    goal = antiderivative_goal(general=True)
    primitive_scope = contract.scope().model_copy(
        update={"requires_general_antiderivative": False}
    )

    assert scope_applicability_findings(primitive_scope.model_dump(mode="json"), goal)
    assert "requested general antiderivative is outside the stored check scope" in (
        _kernel_scope_findings(contract, primitive_scope, goal)
    )


def test_primitive_goal_is_not_covered_by_a_general_scope():
    contract = kernel_contract(ANTIDERIVATIVE)
    assert contract is not None
    scope = contract.scope()
    goal = antiderivative_goal(general=False)

    assert "stored check scope requires a general antiderivative" in (
        _kernel_scope_findings(contract, scope, goal)
    )


def test_distractor_builder_does_not_consult_the_checker(
    monkeypatch: pytest.MonkeyPatch,
):
    contract = kernel_contract(DETERMINANT)
    assert contract is not None
    problem = determinant_problem()
    expected = kernel_expected_answer(DETERMINANT, problem)
    answer_text = kernel_render_answer(DETERMINANT, expected)

    monkeypatch.setattr(structured, "kernel_check_answer", lambda *args: True)

    selected = structured._distinct_distractors(
        contract, problem, expected, answer_text, 3, seed=11
    )

    assert len(selected) == 3
    rendered = [kernel_render_answer(DETERMINANT, item) for item in selected]
    assert len(set(rendered)) == 3
    assert answer_text not in rendered


def test_sampled_assignments_respects_its_limit_and_is_deterministic():
    family = determinant_family()
    boundaries = boundary_assignments(family)
    assert len(boundaries) > 3

    sampled = sampled_assignments(family, seed=5, limit=3)

    assert len(sampled) == 3
    assert sampled == boundaries[:3]
    assert sampled == sampled_assignments(family, seed=5, limit=3)
    assert len(sampled_assignments(family, seed=5, limit=1)) == 1
    assert sampled_assignments(family, seed=5, limit=0) == []
