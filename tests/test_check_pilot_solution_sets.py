"""Independent real solution-set oracle and contract applicability regressions."""

from __future__ import annotations

import pytest
import sympy

from edcraft_validator.application.check_pilot.contracts import (
    EQUATION_CONTRACT,
    applicability_findings,
    get_contract,
    scope_applicability_findings,
    template_goal,
)
from edcraft_validator.application.check_pilot.models import (
    CoefficientDomain,
    ContractScope,
    PilotTemplateDefinition,
    PolynomialFamily,
    StructuredGoal,
)
from edcraft_validator.application.check_pilot.solution_sets import (
    IntervalComponent,
    SolutionSet,
    render_solution_set,
    sets_equal,
    solve_relation_independently,
    solve_relation_via_sympy,
)


def test_negative_repeated_root_inequalities_use_the_correct_sign():
    strict = solve_relation_independently("lt", (0, 0, -1))
    assert not strict.is_all_real
    assert strict.components == (
        IntervalComponent(None, 0, False, False),
        IntervalComponent(0, None, False, False),
    )
    assert render_solution_set(strict) == "(-∞, 0) ∪ (0, ∞)"

    inclusive = solve_relation_independently("le", (0, 0, -1))
    assert inclusive.is_all_real

    assert solve_relation_independently("gt", (0, 0, -1)).is_empty
    assert solve_relation_independently("ge", (0, 0, -1)) == SolutionSet(
        (IntervalComponent(0, 0, True, True),)
    )


@pytest.mark.parametrize(
    ("relation", "lower", "upper", "lower_closed", "upper_closed"),
    [
        ("gt", None, "1/2", False, False),
        ("ge", None, "1/2", False, True),
        ("lt", "1/2", None, False, False),
        ("le", "1/2", None, True, False),
    ],
)
def test_negative_linear_inequality_endpoints_are_correct(
    relation, lower, upper, lower_closed, upper_closed
):
    solution = solve_relation_independently(relation, (2, -4))
    assert len(solution.components) == 1
    component = solution.components[0]
    assert component.lower == (None if lower is None else sympy.Rational(1, 2))
    assert component.upper == (None if upper is None else sympy.Rational(1, 2))
    assert component.lower_closed is lower_closed
    assert component.upper_closed is upper_closed
    assert sets_equal(solution, solve_relation_via_sympy(relation, (2, -4)))


@pytest.mark.parametrize(
    ("relation", "coefficients"),
    [
        ("eq", (6, -5, 1)),
        ("eq", (9, -6, 1)),
        ("eq", (1, 0, 1)),
        ("le", (0, 0, 1)),
        ("ge", (-1, 0, 1)),
        ("gt", (0, 0, -1)),
        ("lt", (0, 0, -1)),
        ("le", (0, 0, -1)),
        ("lt", (0, -2)),
        ("lt", (0, 0, 1)),
        ("ge", (0, 0, 1)),
        ("ge", (2, -4)),
        ("eq", (1, -4, -1)),
    ],
)
def test_independent_oracle_agrees_with_separate_sympy_solver(relation, coefficients):
    independent = solve_relation_independently(relation, coefficients)
    assert sets_equal(independent, solve_relation_via_sympy(relation, coefficients))


@pytest.mark.parametrize("degree", [1, 2, 3, 4, 5])
def test_differentiation_template_goal_uses_the_exact_family_degree(degree):
    family = PolynomialFamily(
        degree=degree,
        coefficients=[
            CoefficientDomain(exponent=exponent, values=[-1, 1])
            for exponent in range(degree)
        ]
        + [CoefficientDomain(exponent=degree, values=[1])],
    )
    definition = PilotTemplateDefinition.model_validate(
        {
            "schema_version": "pilot-template/2",
            "renderer_version": "polynomial-mcq/1",
            "scope": get_contract("polynomial.differentiate/1")
            .scope()
            .model_dump(mode="json"),
            "contract_id": "polynomial.differentiate/1",
            "family": family.model_dump(mode="json"),
        }
    )
    goal = template_goal(definition)
    assert goal.min_degree == degree
    assert goal.max_degree == degree


def test_applicability_rejects_a_scope_that_omits_mandatory_policy():
    contract = get_contract(EQUATION_CONTRACT)
    assert contract is not None
    scope = ContractScope(
        contract_id=EQUATION_CONTRACT,
        operation="solve",
        relations=["eq"],
        min_degree=0,
        max_degree=2,
        max_abs_coefficient=20,
        answer_type="solution_set",
        required_policy=["complete_correctness"],
    )
    goal = StructuredGoal(
        operation="solve",
        relation="eq",
        min_degree=0,
        max_degree=2,
        max_abs_coefficient=20,
        answer_type="solution_set",
        requires_complete_solution_set=True,
    )
    findings = scope_applicability_findings(scope.model_dump(mode="json"), goal)
    assert findings
    assert applicability_findings(contract, goal) == []
    assert any("policy" in finding for finding in findings)
