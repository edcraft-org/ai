"""Independent real solution-set oracle and contract applicability regressions."""

from __future__ import annotations

import pytest
import sympy

from edcraft_validator.application.check_pilot.contracts import (
    EQUATION_CONTRACT,
    INEQUALITY_CONTRACT,
    applicability_findings,
    get_contract,
    scope_applicability_findings,
    scope_from_recipe_operation_set,
    template_goal,
)
from edcraft_validator.application.check_pilot.isolation import PilotWorkerError
from edcraft_validator.application.check_pilot.models import (
    SOLVE_RECIPE_OPERATION_SET,
    CheckRecipeDefinition,
    CoefficientDomain,
    ContractScope,
    PilotTemplateDefinition,
    PolynomialFamily,
    PolynomialRelation,
    RealSetComponent,
    RealSolutionSet,
    RecipeArgument,
    RecipeStep,
    StructuredGoal,
)
from edcraft_validator.application.check_pilot.qualification import (
    execute_recipe_cases_isolated,
    execute_recipe_isolated,
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


def solve_recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        operation_set=SOLVE_RECIPE_OPERATION_SET,
        steps=[
            RecipeStep(
                id="s1",
                operation="relation.solve_real",
                version="1",
                arguments={"problem": RecipeArgument(source="input", name="problem")},
            ),
            RecipeStep(
                id="out",
                operation="set.equal",
                version="1",
                arguments={
                    "expected": RecipeArgument(source="step", name="s1"),
                    "actual": RecipeArgument(source="input", name="candidate"),
                },
            ),
        ],
        output="out",
    )


def inequality_case() -> tuple[PolynomialRelation, RealSolutionSet]:
    problem = PolynomialRelation(relation="gt", coefficients=[-1, 1])
    candidate = RealSolutionSet(
        components=[
            RealSetComponent(
                lower="1",
                upper=None,
                lower_closed=False,
                upper_closed=False,
            )
        ]
    )
    return problem, candidate


def test_standalone_solve_scope_defaults_to_the_equation_contract():
    default = scope_from_recipe_operation_set(SOLVE_RECIPE_OPERATION_SET)
    assert default.contract_id == EQUATION_CONTRACT
    assert default.relations == ["eq"]

    inequality = scope_from_recipe_operation_set(
        SOLVE_RECIPE_OPERATION_SET,
        contract_id=INEQUALITY_CONTRACT,
    )
    assert inequality.contract_id == INEQUALITY_CONTRACT
    assert inequality.relations == ["lt", "le", "gt", "ge"]


def test_isolated_execution_requires_an_explicit_inequality_scope():
    problem, candidate = inequality_case()
    inequality_scope = get_contract(INEQUALITY_CONTRACT).scope()
    equation_scope = get_contract(EQUATION_CONTRACT).scope()

    with pytest.raises(PilotWorkerError, match="outside the check contract"):
        execute_recipe_isolated(solve_recipe(), problem, candidate)
    with pytest.raises(PilotWorkerError, match="outside the check contract"):
        execute_recipe_isolated(
            solve_recipe(),
            problem,
            candidate,
            scope=equation_scope,
        )

    result = execute_recipe_isolated(
        solve_recipe(),
        problem,
        candidate,
        scope=inequality_scope,
    )
    assert result.verdict is True
    assert result.problem == "x - 1 > 0"

    results = execute_recipe_cases_isolated(
        solve_recipe(),
        [(problem, candidate)],
        scope=inequality_scope,
    )
    assert [item.verdict for item in results] == [True]


def test_isolated_execution_rejects_a_handbuilt_contract_scope():
    problem, candidate = inequality_case()
    handbuilt = (
        get_contract(INEQUALITY_CONTRACT)
        .scope()
        .model_copy(update={"relations": ["eq"]})
    )

    with pytest.raises(PilotWorkerError, match="not a trusted contract scope"):
        execute_recipe_isolated(
            solve_recipe(),
            problem,
            candidate,
            scope=handbuilt,
        )


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
        min_degree=1,
        max_degree=2,
        max_abs_coefficient=20,
        answer_type="solution_set",
        requires_complete_solution_set=True,
    )
    findings = scope_applicability_findings(scope.model_dump(mode="json"), goal)
    assert findings
    assert applicability_findings(contract, goal) == []
    assert any("policy" in finding for finding in findings)
