"""End-to-end integration for the eleven registry-backed mathematics checks.

The kernel implementations are loaded through the single registry, not imported
directly. Problem shapes and answer shapes below mirror the domain kernels'
closed models; the registry decides validity.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_check_pilot_application import app

from edcraft_validator.application.check_pilot.kernel_registry import (
    KERNEL_CONTRACT_IDS,
    kernel_contract,
    kernel_expected_answer,
    kernel_problem_strategy,
    kernel_wrong_answers,
)
from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    CheckPlanProposal,
    CheckRecipeDefinition,
    KernelGoal,
    NumericBinding,
    PilotQualificationSettings,
    RecipeArgument,
    RecipeStep,
    StructuredProblemFamily,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.operations import (
    RecipeCompileError,
    compile_recipe,
    execute_recipe,
)
from edcraft_validator.application.check_pilot.qualification import qualify_recipe
from edcraft_validator.application.check_pilot.structured import family_assignment_count

CONTRACTS = list(KERNEL_CONTRACT_IDS)
# One representative, deliberately small authored family per contract. Bindings
# stay valid for every listed value; application validation decides.
FAMILIES: dict[str, tuple[dict[str, object], list[tuple[str, list[int]]]]] = {
    "polynomial.antiderivative/1": (
        {
            "kind": "polynomial_antiderivative",
            "coefficients": ["2", "0", "3"],
            "general": True,
        },
        [("coefficients.0", [1, 2, 3]), ("coefficients.2", [1, 3])],
    ),
    "polynomial.definite-integral/1": (
        {
            "kind": "polynomial_definite_integral",
            "coefficients": ["1", "0", "2"],
            "lower": "0",
            "upper": "2",
        },
        [("upper", [2, 3])],
    ),
    "expression.differentiate/1": (
        {
            "kind": "expression_differentiate",
            "expression": {
                "op": "mul",
                "args": [{"sym": "x"}, {"op": "sin", "args": [{"sym": "x"}]}],
            },
            "symbols": [{"name": "x", "positive": False, "nonzero": False}],
        },
        [],
    ),
    "polynomial.expand/1": (
        {
            "kind": "polynomial-expand",
            "expression": {
                "op": "mul",
                "args": [
                    {"op": "sub", "args": [{"sym": "x"}, {"num": "1"}]},
                    {"op": "add", "args": [{"sym": "x"}, {"num": "1"}]},
                ],
            },
        },
        [
            ("expression.args.0.args.1.num", [1, 2]),
            ("expression.args.1.args.1.num", [1, 3]),
        ],
    ),
    "polynomial.factor/1": (
        {
            "kind": "polynomial-factor",
            "expression": {
                "op": "sub",
                "args": [
                    {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                    {"num": "1"},
                ],
            },
        },
        [("expression.args.1.num", [-1, -4])],
    ),
    "polynomial.complete-square/1": (
        {
            "kind": "polynomial-complete-square",
            "expression": {
                "op": "add",
                "args": [
                    {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                    {"op": "mul", "args": [{"num": "4"}, {"sym": "x"}]},
                    {"num": "1"},
                ],
            },
        },
        [("expression.args.1.args.0.num", [4, 6])],
    ),
    "linear-system.unique/1": (
        {
            "kind": "linear-system-unique",
            "matrix": [[2, 1], [1, 3]],
            "rhs": [1, 2],
        },
        [("matrix.0.0", [2, 3])],
    ),
    "matrix.multiply/1": (
        {
            "kind": "matrix_multiply",
            "left": [["1", "2"], ["3", "4"]],
            "right": [["5", "6"], ["7", "8"]],
        },
        [("left.0.0", [1, 2])],
    ),
    "matrix.determinant/1": (
        {"kind": "matrix_determinant", "matrix": [["1", "2"], ["3", "4"]]},
        [("matrix.0.0", [1, 2])],
    ),
    "matrix.inverse/1": (
        {"kind": "matrix_inverse", "matrix": [["2", "0"], ["0", "3"]]},
        [("matrix.0.0", [2, 3])],
    ),
    "matrix.lu/1": (
        {"kind": "matrix_lu", "matrix": [["2", "1"], ["4", "3"]]},
        [("matrix.0.0", [2, 5])],
    ),
}
assert set(FAMILIES) == set(CONTRACTS)


def structured_recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        operation_set="structured-check/1",
        steps=[
            RecipeStep(
                id="e1",
                operation="structured.expected",
                version="1",
                arguments={"problem": RecipeArgument(source="input", name="problem")},
            ),
            RecipeStep(
                id="out",
                operation="structured.accepts",
                version="1",
                arguments={
                    "expected": RecipeArgument(source="step", name="e1"),
                    "problem": RecipeArgument(source="input", name="problem"),
                    "candidate": RecipeArgument(source="input", name="candidate"),
                },
            ),
        ],
        output="out",
    )


def kernel_plan(contract_id: str) -> CheckPlanProposal:
    contract = kernel_contract(contract_id)
    assert contract is not None
    return CheckPlanProposal(
        contract_id=contract_id,
        reason="The request names a supported bounded mathematics check.",
        goal=KernelGoal(
            operation=contract.operation,
            answer_type=contract.answer_type,
            min_degree=contract.min_degree,
            max_degree=contract.max_degree,
            max_abs_coefficient=contract.max_abs_coefficient,
            min_dimension=contract.min_dimension,
            max_dimension=contract.max_dimension,
            requires_general_antiderivative=(
                contract_id == "polynomial.antiderivative/1"
            ),
            domain_assumptions=list(contract.domain_assumptions),
        ),
    )


def family_for(
    contract_id: str, *, num_distractors: int = 3
) -> StructuredProblemFamily:
    problem, bindings = FAMILIES[contract_id]
    return StructuredProblemFamily(
        contract_id=contract_id,
        problem=copy.deepcopy(problem),
        bindings=[
            NumericBinding(path=path, values=values) for path, values in bindings
        ],
        num_distractors=num_distractors,
    )


def kernel_check(contract_id: str, *, num_distractors: int = 3) -> CheckAuthorProposal:
    return CheckAuthorProposal(
        title=f"Check {contract_id}",
        description="Compare a candidate answer with an independent kernel oracle.",
        recipe=structured_recipe(),
    )


def kernel_template(
    contract_id: str, *, num_distractors: int = 3
) -> TemplateAuthorProposal:
    return TemplateAuthorProposal(
        contract_id=contract_id,
        structured_family=family_for(contract_id, num_distractors=num_distractors),
    )


class KernelScriptedProvider:
    provider = "stub"
    model = "stub-structured-kernels"

    def __init__(self, contract_id: str) -> None:
        self.contract_id = contract_id

    def generation_settings(self):
        return {"mode": "scripted", "reasoning_effort": "none"}

    def generate(self, request):
        if request.prompt_version.startswith("check-planner"):
            return kernel_plan(self.contract_id)
        if request.prompt_version.startswith("check-author"):
            return kernel_check(self.contract_id)
        return kernel_template(self.contract_id)


def small_settings() -> PilotQualificationSettings:
    return PilotQualificationSettings(
        max_examples=10, max_execution_calls=400, timeout_seconds=30.0
    )


def test_registry_contract_ids_cover_the_agreed_eleven():
    assert set(KERNEL_CONTRACT_IDS) == {
        "polynomial.antiderivative/1",
        "polynomial.definite-integral/1",
        "expression.differentiate/1",
        "polynomial.expand/1",
        "polynomial.factor/1",
        "polynomial.complete-square/1",
        "linear-system.unique/1",
        "matrix.multiply/1",
        "matrix.determinant/1",
        "matrix.inverse/1",
        "matrix.lu/1",
    }
    for contract_id in KERNEL_CONTRACT_IDS:
        contract = kernel_contract(contract_id)
        assert contract is not None
        assert contract.contract_id == contract_id
        assert contract.kind
        assert contract.answer_type


@pytest.mark.parametrize("contract_id", CONTRACTS)
def test_every_kernel_contract_accepts_its_oracle_and_rejects_distractors(
    contract_id: str,
):
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_check_answer,
        kernel_validate_problem,
    )

    problem = copy.deepcopy(FAMILIES[contract_id][0])
    kernel_validate_problem(contract_id, problem)
    expected = kernel_expected_answer(contract_id, problem)

    assert kernel_check_answer(contract_id, problem, expected) is True

    wrongs = kernel_wrong_answers(contract_id, problem, expected)
    assert len(wrongs) >= 5
    rendered = {json.dumps(item, sort_keys=True) for item in wrongs}
    assert len(rendered) == len(wrongs)
    for wrong in wrongs:
        assert kernel_check_answer(contract_id, problem, wrong) is False


@pytest.mark.parametrize("contract_id", CONTRACTS)
def test_kernel_problem_strategy_and_boundaries_produce_valid_problems(
    contract_id: str,
):
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_boundary_problems,
        kernel_validate_problem,
    )

    strategy = kernel_problem_strategy(contract_id)
    assert strategy is not None
    boundaries = kernel_boundary_problems(contract_id)
    assert boundaries
    for problem in boundaries:
        kernel_validate_problem(contract_id, problem)


@pytest.mark.parametrize("contract_id", CONTRACTS)
def test_kernel_structured_recipe_qualifies_independently(contract_id: str):
    qualification = qualify_recipe(
        structured_recipe(),
        seed=23,
        settings=small_settings(),
        scope=kernel_contract(contract_id).scope(),
    )
    assert qualification.status == "passed", qualification.findings
    assert qualification.accepted_cases >= 2


@pytest.mark.parametrize("contract_id", CONTRACTS)
def test_full_author_approve_generate_and_reuse_for_every_contract(
    tmp_path: Path, contract_id: str
):
    application = app(tmp_path, max_examples=10)
    provider = KernelScriptedProvider(contract_id)

    record = application.author_template(
        "owner", prompt=f"Author {contract_id}", provider=provider
    )

    assert record.status == "ready", record.findings
    assert record.template is not None
    assert record.template["schema_version"] == "pilot-template/3"
    assert record.template["goal"] == kernel_plan(contract_id).goal.model_dump(
        mode="json"
    )
    assert record.check is not None
    assert record.check.scope["contract_id"] == contract_id
    selection = record.selection
    assert selection is not None and selection.contract_id == contract_id

    application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    quantity = min(3, family_assignment_count(family_for(contract_id)))
    batch = application.generate("owner", record.template_id, seed=7, quantity=quantity)
    assert len(batch.questions) == quantity
    assert batch.shortfall == 0
    assert all(
        question.check_ref == record.check.check_ref for question in batch.questions
    )

    reused = application.author_template(
        "owner", prompt=f"Reuse {contract_id}", provider=provider
    )
    assert reused.status == "ready", reused.findings
    assert reused.reused_check is True
    assert reused.check is not None
    assert reused.check.check_ref == record.check.check_ref


def test_compiler_rejects_structured_recipe_without_expected_oracle_step():
    recipe = CheckRecipeDefinition(
        operation_set="structured-check/1",
        steps=[
            RecipeStep(
                id="out",
                operation="structured.accepts",
                version="1",
                arguments={
                    "expected": RecipeArgument(source="input", name="candidate"),
                    "problem": RecipeArgument(source="input", name="problem"),
                    "candidate": RecipeArgument(source="input", name="candidate"),
                },
            )
        ],
        output="out",
    )
    with pytest.raises(RecipeCompileError):
        compile_recipe(recipe, scope=kernel_contract("matrix.determinant/1").scope())


def test_structured_recipe_executes_structured_problem_and_candidate():
    contract = kernel_contract("matrix.determinant/1")
    problem = copy.deepcopy(FAMILIES["matrix.determinant/1"][0])
    expected = kernel_expected_answer("matrix.determinant/1", problem)
    compiled = compile_recipe(structured_recipe(), scope=contract.scope())

    result = execute_recipe(compiled, problem, expected)

    assert result.verdict is True
    assert result.expected
    assert result.problem


def test_antiderivative_distinguishes_one_primitive_from_general_answer():
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_check_answer,
    )

    primitive_problem = {
        "kind": "polynomial_antiderivative",
        "coefficients": ["2", "3"],
        "general": False,
    }
    general_problem = {**primitive_problem, "general": True}
    primitive = {
        "kind": "polynomial_antiderivative_answer",
        "coefficients": ["0", "2", "3/2"],
        "general": False,
    }
    general = {**primitive, "general": True}

    assert kernel_check_answer(
        "polynomial.antiderivative/1", primitive_problem, primitive
    )
    assert not kernel_check_answer(
        "polynomial.antiderivative/1", general_problem, primitive
    )
    assert kernel_check_answer("polynomial.antiderivative/1", general_problem, general)


def test_factorisation_rejects_unchanged_and_identity_factor_evasions():
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_check_answer,
    )

    problem = {
        "kind": "polynomial-factor",
        "expression": {
            "op": "sub",
            "args": [
                {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                {"num": "1"},
            ],
        },
    }
    expanded = {
        "expression": {
            "op": "sub",
            "args": [
                {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                {"num": "1"},
            ],
        },
    }
    identity = {
        "expression": {
            "op": "mul",
            "args": [
                {"num": "1"},
                {
                    "op": "sub",
                    "args": [{"sym": "x"}, {"num": "1"}],
                },
                {
                    "op": "add",
                    "args": [{"sym": "x"}, {"num": "1"}],
                },
            ],
        },
    }
    factored = {
        "expression": {
            "op": "mul",
            "args": [
                {
                    "op": "sub",
                    "args": [{"sym": "x"}, {"num": "1"}],
                },
                {
                    "op": "add",
                    "args": [{"sym": "x"}, {"num": "1"}],
                },
            ],
        },
    }

    assert not kernel_check_answer("polynomial.factor/1", problem, expanded)
    assert not kernel_check_answer("polynomial.factor/1", problem, identity)
    assert kernel_check_answer("polynomial.factor/1", problem, factored)


def test_complete_square_requires_structural_form_not_expanded_quadratic():
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_check_answer,
    )

    problem = {
        "kind": "polynomial-complete-square",
        "expression": {
            "op": "add",
            "args": [
                {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                {"op": "mul", "args": [{"num": "4"}, {"sym": "x"}]},
                {"num": "1"},
            ],
        },
    }
    expanded = {
        "expression": {
            "op": "add",
            "args": [
                {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                {"op": "mul", "args": [{"num": "4"}, {"sym": "x"}]},
                {"num": "1"},
            ],
        },
    }
    completed = {
        "expression": {
            "op": "add",
            "args": [
                {
                    "op": "pow",
                    "args": [
                        {
                            "op": "add",
                            "args": [{"sym": "x"}, {"num": "2"}],
                        },
                        {"num": "2"},
                    ],
                },
                {"num": "-3"},
            ],
        },
    }

    assert not kernel_check_answer("polynomial.complete-square/1", problem, expanded)
    assert kernel_check_answer("polynomial.complete-square/1", problem, completed)


def test_lu_rejects_invalid_permutation_even_with_plausible_products():
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_check_answer,
    )

    problem = copy.deepcopy(FAMILIES["matrix.lu/1"][0])
    expected = kernel_expected_answer("matrix.lu/1", problem)
    broken = copy.deepcopy(expected)
    broken["permutation"] = [["1", "1"], ["0", "0"]]

    assert not kernel_check_answer("matrix.lu/1", problem, broken)


def test_structured_author_schema_is_closed_and_rejects_unknown_fields():
    schema = TemplateAuthorProposal.model_json_schema()
    text = json.dumps(schema)
    assert "additionalProperties" in text

    with pytest.raises(ValueError):
        StructuredProblemFamily.model_validate(
            {
                "contract_id": "matrix.determinant/1",
                "problem": {
                    "kind": "matrix_determinant",
                    "matrix": [["1", "2"], ["3", "4"]],
                    "unexpected": 1,
                },
                "bindings": [],
                "num_distractors": 3,
            }
        )
