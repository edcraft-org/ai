"""Sampled families must preserve the mathematical goal of the request."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_check_pilot_math_checks_integration import (
    KernelScriptedProvider,
    kernel_plan,
)

from edcraft_validator.application.check_pilot import CheckPilotApplication
from edcraft_validator.application.check_pilot import algebra_checks as algebra
from edcraft_validator.application.check_pilot import calculus_checks as calculus
from edcraft_validator.application.check_pilot import matrix_checks as matrices
from edcraft_validator.application.check_pilot.kernel_registry import kernel_contract
from edcraft_validator.application.check_pilot.models import (
    CheckPlanProposal,
    KernelGoal,
    NumericBinding,
    PilotTemplateDefinition,
    StructuredProblemFamily,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.structured import (
    problem_goal_findings,
)


def factor_problem(leading: str = "1") -> dict:
    return {
        "kind": "polynomial-factor",
        "expression": {
            "op": "add",
            "args": [
                {
                    "op": "mul",
                    "args": [
                        {"num": leading},
                        {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                    ],
                },
                {"sym": "x"},
                {"num": "1"},
            ],
        },
    }


def test_interior_zero_cannot_turn_a_quadratic_request_into_linear_questions(
    tmp_path: Path,
):
    contract_id = "polynomial.factor/1"
    family = StructuredProblemFamily(
        contract_id=contract_id,
        problem=factor_problem(),
        bindings=[
            NumericBinding(path="expression.args.0.args.0.num", values=[-1, 0, 1])
        ],
    )

    class Provider(KernelScriptedProvider):
        def generate(self, request):
            if request.schema_name == "check_plan":
                plan = kernel_plan(contract_id)
                return CheckPlanProposal(
                    contract_id=contract_id,
                    goal=plan.goal.model_copy(
                        update={"min_degree": 2, "max_degree": 2}
                    ),
                    reason="Quadratic factorisation only.",
                )
            if request.schema_name == "polynomial_family":
                return TemplateAuthorProposal(
                    contract_id=contract_id, structured_family=family
                )
            return super().generate(request)

    application = CheckPilotApplication(tmp_path)
    record = application.author_template(
        "owner",
        prompt="Factor quadratic polynomials only, exactly degree two.",
        provider=Provider(contract_id),
    )
    assert record.status in {"needs_review", "error"}, (
        "A zero leading coefficient inside the parameter domain produces a linear "
        "question; boundary assignments alone do not establish the degree promise."
    )


def test_algebra_extent_uses_mathematical_degree_after_cancellation():
    problem = {
        "kind": "polynomial-factor",
        "expression": {
            "op": "add",
            "args": [
                {
                    "op": "sub",
                    "args": [
                        {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                        {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                    ],
                },
                {"sym": "x"},
            ],
        },
    }
    assert algebra.problem_extent("polynomial.factor/1", problem)["max_degree"] == 1


def test_algebra_extent_uses_expanded_coefficients_instead_of_numeric_leaves():
    problem = {
        "kind": "polynomial-expand",
        "expression": {
            "op": "pow",
            "args": [
                {"op": "add", "args": [{"sym": "x"}, {"num": "20"}]},
                {"num": "2"},
            ],
        },
    }
    extent = algebra.problem_extent("polynomial.expand/1", problem)
    assert extent["max_degree"] == 2
    assert extent["max_abs_coefficient"] == 400


def test_calculus_extent_uses_actual_degree_and_general_answer_requirement():
    extent = calculus.problem_extent(
        "polynomial.antiderivative/1",
        {
            "kind": "polynomial_antiderivative",
            "coefficients": ["1", "0", "0"],
            "general": True,
        },
    )
    assert extent["min_degree"] == extent["max_degree"] == 0
    assert extent["requires_general"] is True


def test_matrix_extent_keeps_both_rectangular_dimensions():
    extent = matrices.problem_extent(
        "matrix.multiply/1",
        {
            "kind": "matrix_multiply",
            "left": [["1", "2", "3"]],
            "right": [["1"], ["2"], ["3"]],
        },
    )
    assert extent["min_dimension"] == 1
    assert extent["max_dimension"] == 3


def quadratic_factor_goal(contract) -> KernelGoal:
    return KernelGoal(
        operation=contract.operation,
        answer_type=contract.answer_type,
        min_degree=2,
        max_degree=2,
        max_abs_coefficient=contract.max_abs_coefficient,
        max_dimension=contract.max_dimension,
    )


def test_runtime_goal_guard_rejects_an_out_of_goal_concrete_problem():
    contract = kernel_contract("polynomial.factor/1")
    assert contract is not None
    goal = quadratic_factor_goal(contract)

    assert problem_goal_findings(contract.contract_id, goal, factor_problem("0"))
    assert problem_goal_findings(contract.contract_id, goal, factor_problem("1")) == []


def test_version_three_template_keeps_the_validated_plan_goal():
    contract = kernel_contract("polynomial.factor/1")
    assert contract is not None
    goal = quadratic_factor_goal(contract)
    family = StructuredProblemFamily(
        contract_id=contract.contract_id,
        problem=factor_problem(),
        bindings=[
            NumericBinding(
                path="expression.args.0.args.0.num",
                values=[1, 2],
            )
        ],
    )
    payload = {
        "schema_version": "pilot-template/3",
        "renderer_version": "structured-mcq/1",
        "scope": contract.scope(),
        "contract_id": contract.contract_id,
        "structured_family": family,
    }

    with pytest.raises(ValidationError):
        PilotTemplateDefinition(**payload)

    definition = PilotTemplateDefinition(**payload, goal=goal)
    assert definition.goal == goal
    assert definition.model_dump(mode="json", exclude_none=True)["goal"] == (
        goal.model_dump(mode="json")
    )
