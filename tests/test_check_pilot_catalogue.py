"""Planning, catalogue selection, author/qualify/store and reuse regressions."""

from __future__ import annotations

from pathlib import Path

from test_check_pilot_application import (
    ScriptedProvider,
    app,
    author,
    valid_check_proposal,
    valid_plan,
    valid_recipe,
    valid_template_proposal,
)

from edcraft_validator.application.check_pilot import CheckPilotApplication
from edcraft_validator.application.check_pilot.contracts import contract_catalogue
from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    CheckPlanProposal,
    CheckRecipeDefinition,
    CheckRef,
    CoefficientDomain,
    PilotQualificationSettings,
    RecipeArgument,
    RecipeStep,
    SolveFamily,
    StructuredGoal,
    TemplateAuthorProposal,
)

DOC = "polynomial.differentiate/1"
EQUATION = "polynomial.equation-real/1"
INEQUALITY = "polynomial.inequality-real/1"


def solve_recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        operation_set="polynomial-solve-real/1",
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


def solve_check_proposal() -> CheckAuthorProposal:
    return CheckAuthorProposal(
        title="Solve a bounded real polynomial relation",
        description="Compare the complete real solution set with the candidate set.",
        recipe=solve_recipe(),
    )


def solve_template_proposal(
    *,
    contract_id: str = EQUATION,
    relation: str = "eq",
    degree: int = 2,
    constants: list[int] | None = None,
    leading: list[int] | None = None,
) -> TemplateAuthorProposal:
    return TemplateAuthorProposal(
        contract_id=contract_id,
        solve_family=SolveFamily(
            relation=relation,
            degree=degree,
            coefficients=[
                CoefficientDomain(exponent=0, values=constants or [-4, -1, 0, 1, 4]),
                *[
                    CoefficientDomain(exponent=exponent, values=[-3, -1, 0, 1, 3])
                    for exponent in range(1, degree)
                ],
                CoefficientDomain(exponent=degree, values=leading or [2, 1, -1, -2]),
            ],
            num_distractors=3,
        ),
    )


def solve_plan(
    *,
    contract_id: str = EQUATION,
    relation: str = "eq",
    min_degree: int = 1,
    max_degree: int = 2,
    saved_check_ref: CheckRef | None = None,
    supported: bool = True,
    development_needed: str | None = None,
) -> CheckPlanProposal:
    if not supported:
        return CheckPlanProposal(supported=False, development_needed=development_needed)
    return CheckPlanProposal(
        contract_id=contract_id,
        reason="Compute the complete real solution set for the stated relation.",
        goal=StructuredGoal(
            operation="solve",
            relation=relation,
            min_degree=min_degree,
            max_degree=max_degree,
            max_abs_coefficient=20,
            answer_type="solution_set",
            requires_complete_solution_set=True,
        ),
        saved_check_ref=saved_check_ref,
    )


def equation_provider(**kwargs) -> ScriptedProvider:
    return ScriptedProvider(
        plan=solve_plan(),
        check=solve_check_proposal(),
        template=solve_template_proposal(),
        **kwargs,
    )


def test_model_contract_descriptors_advertise_template_degree_minimum_one():
    descriptors = {item["contract_id"]: item for item in contract_catalogue()}

    for contract_id in (EQUATION, INEQUALITY):
        descriptor = descriptors[contract_id]
        assert descriptor["min_degree"] == 1
        assert descriptor["check_min_degree"] == 0
        assert descriptor["max_degree"] == 2

    differentiation = descriptors[DOC]
    assert differentiation["min_degree"] == 1
    assert differentiation["check_min_degree"] == 1


def test_degree_zero_solve_plan_is_rejected_before_authoring(tmp_path: Path):
    provider = ScriptedProvider(
        plan=solve_plan(min_degree=0, max_degree=0),
        check=solve_check_proposal(),
        template=solve_template_proposal(),
    )
    application = app(tmp_path)

    record = author(
        application,
        provider,
        prompt="Solve the constant equation 3 = 0",
    )

    assert record.status == "needs_review"
    assert record.check is None
    assert record.template is None
    assert any("minimum degree" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-planner"] * 3
    assert application.list_checks("owner") == []


def test_explicit_saved_reference_reuses_exact_check_and_records_selection(
    tmp_path: Path,
):
    application = app(tmp_path)
    first = author(application, ScriptedProvider())
    assert first.status == "ready"
    assert first.check is not None

    reference = first.check.check_ref
    provider = ScriptedProvider(plan=valid_plan(saved_check_ref=reference))
    second = author(
        application,
        provider,
        prompt="Author a second template from the saved derivative check",
    )

    assert second.status == "ready"
    assert second.reused_check is True
    assert second.check is not None
    assert second.check.check_ref == reference
    assert [call["role"] for call in provider.calls] == [
        "check-planner",
        "template-author",
    ]
    assert second.selection is not None
    assert second.selection.contract_id == DOC
    assert second.selection.source == "saved"
    assert second.selection.check_ref == reference
    assert second.selection.reason == valid_plan().reason
    assert len(application.list_checks("owner")) == 1


def test_mixed_catalogue_selects_only_an_applicable_contract_and_scope(
    tmp_path: Path,
):
    application = app(tmp_path)
    differentiation = author(application, ScriptedProvider())
    equation = author(
        application,
        equation_provider(),
        prompt="Solve a bounded quadratic equation completely",
    )
    assert differentiation.check is not None
    assert equation.check is not None
    assert equation.reused_check is False
    assert equation.check.check_ref != differentiation.check.check_ref
    # The stored check scope deliberately covers the constant degree-0 boundary,
    # even though authored templates start at degree 1.
    assert equation.check.scope["min_degree"] == 0
    assert len(application.list_checks("owner")) == 2

    differentiation_again = author(
        application,
        ScriptedProvider(),
        prompt="Differentiate another bounded polynomial",
    )
    assert differentiation_again.reused_check is True
    assert differentiation_again.check is not None
    assert differentiation_again.check.check_ref == differentiation.check.check_ref
    assert differentiation_again.selection is not None
    assert differentiation_again.selection.contract_id == DOC

    equation_again = author(
        application,
        equation_provider(),
        prompt="Solve another bounded quadratic equation completely",
    )
    assert equation_again.reused_check is True
    assert equation_again.check is not None
    assert equation_again.check.check_ref == equation.check.check_ref
    assert equation_again.check.scope["min_degree"] == 0
    assert equation_again.selection is not None
    assert equation_again.selection.contract_id == EQUATION

    inequality = author(
        application,
        ScriptedProvider(
            plan=solve_plan(contract_id=INEQUALITY, relation="ge"),
            check=solve_check_proposal(),
            template=solve_template_proposal(contract_id=INEQUALITY, relation="ge"),
        ),
        prompt="Solve a bounded quadratic inequality completely",
    )
    assert inequality.reused_check is False
    assert inequality.check is not None
    assert inequality.check.check_ref not in {
        differentiation.check.check_ref,
        equation.check.check_ref,
    }
    assert inequality.selection is not None
    assert inequality.selection.contract_id == INEQUALITY
    assert len(application.list_checks("owner")) == 3


def test_unknown_saved_reference_fails_closed_without_authoring_or_substitution(
    tmp_path: Path,
):
    application = app(tmp_path)
    unknown = CheckRef(
        check_id="chk_" + "a" * 24,
        version="1",
        sha256="a" * 64,
    )
    provider = ScriptedProvider(plan=valid_plan(saved_check_ref=unknown))
    record = author(application, provider)

    assert record.status == "needs_review"
    assert record.check is None
    assert record.template is None
    assert any("not found" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-planner"] * 3
    assert application.list_checks("owner") == []
    assert application.list_templates("owner") == [record]


def test_stale_and_foreign_references_fail_closed(tmp_path: Path):
    application = app(tmp_path)
    first = author(application, ScriptedProvider())
    assert first.check is not None

    stale = first.check.check_ref.model_copy(update={"sha256": "f" * 64})
    stale_provider = ScriptedProvider(plan=valid_plan(saved_check_ref=stale))
    stale_record = author(application, stale_provider)
    assert stale_record.status == "needs_review"
    assert any("stale" in finding for finding in stale_record.findings)
    assert [call["role"] for call in stale_provider.calls] == ["check-planner"] * 3

    other = author(
        application,
        ScriptedProvider(
            check=CheckAuthorProposal(
                title="Another owner's derivative check",
                description=(
                    "A distinct check definition so the foreign reference "
                    "cannot collide with this owner's own content hash."
                ),
                recipe=valid_recipe(),
            )
        ),
        owner="other-owner",
        prompt="Author another owner's derivative template",
    )
    assert other.check is not None
    assert other.check.check_ref != first.check.check_ref
    foreign_provider = ScriptedProvider(
        plan=valid_plan(saved_check_ref=other.check.check_ref)
    )
    foreign_record = author(application, foreign_provider)
    assert foreign_record.status == "needs_review"
    assert any("not found" in finding for finding in foreign_record.findings)
    assert [call["role"] for call in foreign_provider.calls] == ["check-planner"] * 3
    assert len(application.list_checks("owner")) == 1


def test_saved_check_for_a_different_contract_is_rejected_before_authoring(
    tmp_path: Path,
):
    application = app(tmp_path)
    differentiation = author(application, ScriptedProvider())
    assert differentiation.check is not None

    provider = ScriptedProvider(
        plan=solve_plan(saved_check_ref=differentiation.check.check_ref),
        check=valid_check_proposal(),
        template=valid_template_proposal(),
    )
    record = author(application, provider, prompt="Solve a quadratic equation")
    assert record.status == "needs_review"
    assert any("different trusted contract" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-planner"] * 3
    assert len(application.list_checks("owner")) == 1


def test_unsupported_plan_returns_development_needed_without_authoring(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        plan=CheckPlanProposal(
            supported=False,
            development_needed="General polynomial integration is not supported.",
        )
    )
    record = author(app(tmp_path), provider)
    assert record.status == "needs_review"
    assert any("Development needed" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-planner"]
    assert record.check is None


def test_unknown_trusted_contract_fails_closed(tmp_path: Path):
    provider = ScriptedProvider(
        plan=CheckPlanProposal(
            contract_id="polynomial.integration/1",
            reason="Integrate a polynomial.",
            goal=StructuredGoal(
                operation="differentiate",
                relation="none",
                min_degree=1,
                max_degree=5,
                max_abs_coefficient=20,
                answer_type="expression",
            ),
        )
    )
    record = author(app(tmp_path), provider)
    assert record.status == "needs_review"
    assert any("not trusted" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-planner"] * 3
    assert record.check is None


def test_template_below_the_selected_plan_keeps_check_but_blocks_template(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        plan=valid_plan(min_degree=3, max_degree=3),
        template=valid_template_proposal(degree=1),
    )
    application = app(tmp_path)
    record = author(application, provider)

    assert record.status == "needs_review"
    assert record.check is not None
    assert record.template is None
    assert any("below the selected plan" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == [
        "check-planner",
        "check-author",
        "template-author",
        "template-author",
        "template-author",
    ]
    assert record.selection is not None
    assert record.selection.source == "authored"
    assert len(application.list_checks("owner")) == 1


def test_qualification_budget_exhaustion_is_inconclusive_not_a_counterexample(
    tmp_path: Path,
):
    application = CheckPilotApplication(
        tmp_path,
        qualification_settings=PilotQualificationSettings(
            max_examples=4, max_execution_calls=1, timeout_seconds=30.0
        ),
    )
    provider = ScriptedProvider()
    record = author(application, provider)

    assert record.status == "needs_review"
    assert record.check is None
    assert record.check_qualification is not None
    assert record.check_qualification.status == "inconclusive"
    assert record.check_qualification.counterexample is None
    assert any("budget" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == [
        "check-planner",
        "check-author",
        "check-author",
        "check-author",
    ]
    assert application.list_checks("owner") == []


def test_kernel_registry_metadata_matches_module_exported_constants():
    from edcraft_validator.application.check_pilot import algebra_checks as algebra
    from edcraft_validator.application.check_pilot import calculus_checks as calculus
    from edcraft_validator.application.check_pilot import matrix_checks as matrices
    from edcraft_validator.application.check_pilot.kernel_registry import (
        KERNEL_CONTRACT_IDS,
        kernel_contract,
    )

    expected = {
        "polynomial.antiderivative/1": (
            "antiderivative",
            "antiderivative",
            0,
            calculus.MAX_DEGREE,
            calculus.MAX_ABS_COEFFICIENT,
            0,
            0,
        ),
        "polynomial.definite-integral/1": (
            "definite-integral",
            "scalar",
            0,
            calculus.MAX_DEGREE,
            calculus.MAX_ABS_COEFFICIENT,
            0,
            0,
        ),
        "expression.differentiate/1": (
            "differentiate-expression",
            "expression",
            0,
            0,
            calculus.MAX_ABS_COEFFICIENT,
            0,
            0,
        ),
        "polynomial.expand/1": (
            "expand",
            "expression",
            1,
            algebra.MAX_PROBLEM_DEGREE,
            algebra.MAX_EXPANDED_COEFFICIENT,
            0,
            0,
        ),
        "polynomial.factor/1": (
            "factor",
            "expression",
            1,
            algebra.MAX_FACTOR_DEGREE,
            algebra.MAX_EXPANDED_COEFFICIENT,
            0,
            0,
        ),
        "polynomial.complete-square/1": (
            "complete-square",
            "expression",
            2,
            2,
            algebra.MAX_EXPANDED_COEFFICIENT,
            0,
            0,
        ),
        "linear-system.unique/1": (
            "solve-linear-system",
            "tuple",
            0,
            0,
            algebra.MAX_SYSTEM_ENTRY,
            2,
            2,
        ),
        "matrix.multiply/1": (
            "matrix-multiply",
            "matrix",
            0,
            0,
            matrices.MAX_ENTRY_ABS,
            1,
            max(matrices.MAX_ROWS, matrices.MAX_COLUMNS),
        ),
        "matrix.determinant/1": (
            "matrix-determinant",
            "scalar",
            0,
            0,
            matrices.MAX_ENTRY_ABS,
            matrices.MIN_SQUARE_SIZE,
            matrices.MAX_SQUARE_SIZE,
        ),
        "matrix.inverse/1": (
            "matrix-inverse",
            "matrix",
            0,
            0,
            matrices.MAX_ENTRY_ABS,
            matrices.MIN_SQUARE_SIZE,
            matrices.MAX_SQUARE_SIZE,
        ),
        "matrix.lu/1": (
            "matrix-lu",
            "lu-decomposition",
            0,
            0,
            matrices.MAX_ENTRY_ABS,
            matrices.MIN_SQUARE_SIZE,
            matrices.MAX_SQUARE_SIZE,
        ),
    }

    assert set(expected) == set(KERNEL_CONTRACT_IDS)
    for contract_id, bounds in expected.items():
        contract = kernel_contract(contract_id)
        assert contract is not None
        assert (
            contract.operation,
            contract.answer_type,
            contract.min_degree,
            contract.max_degree,
            contract.max_abs_coefficient,
            contract.min_dimension,
            contract.max_dimension,
        ) == bounds
        expected_assumptions = (
            ("Every declared symbol is real; positive implies nonzero.",)
            if contract_id == "expression.differentiate/1"
            else ()
        )
        assert contract.domain_assumptions == expected_assumptions


def test_catalogue_exposes_general_antiderivative_only_where_supported():
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_contract,
    )

    descriptors = {item["contract_id"]: item for item in contract_catalogue()}
    antiderivative = descriptors["polynomial.antiderivative/1"]
    assert antiderivative["requires_general"] is True
    contract = kernel_contract("polynomial.antiderivative/1")
    assert contract is not None
    assert contract.requires_general is True
    assert contract.scope().requires_general_antiderivative is True

    for contract_id, descriptor in descriptors.items():
        if contract_id == "polynomial.antiderivative/1":
            continue
        assert descriptor.get("requires_general") is not True
