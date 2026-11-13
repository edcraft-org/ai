"""Engine-graded check pilot integration: catalogue, flow, evidence, refusal."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_check_pilot_application import app
from test_check_pilot_math_checks_integration import (
    FAMILIES,
    family_for,
    kernel_check,
    kernel_plan,
    small_settings,
    structured_recipe,
)

from edcraft_validator.application.check_pilot.batch_generation import (
    generate_batch as build_generation_batch,
)
from edcraft_validator.application.check_pilot.contracts import (
    contract_catalogue,
    contract_for_scope,
    get_contract,
    is_engine_contract,
    scope_applicability_findings,
)
from edcraft_validator.application.check_pilot.engine_adapter import (
    EngineAdapterGap,
    form_findings,
    to_correctness_request,
)
from edcraft_validator.application.check_pilot.engine_checks import grade_answer
from edcraft_validator.application.check_pilot.engine_registry import (
    ENGINE_CONTRACT_IDS,
    engine_contract,
)
from edcraft_validator.application.check_pilot.errors import PilotConflict
from edcraft_validator.application.check_pilot.kernel_registry import (
    KERNEL_CONTRACT_IDS,
    kernel_contract,
    kernel_expected_answer,
    kernel_wrong_answers,
)
from edcraft_validator.application.check_pilot.models import (
    STRUCTURED_RENDERER_VERSION,
    TEMPLATE_SCHEMA_VERSION_V3,
    CheckPlanProposal,
    CheckRef,
    EngineContractScope,
    KernelGoal,
    PilotQualificationSettings,
    PilotTemplateDefinition,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.storage import PilotStore
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
)

ENGINE = "engine.polynomial.factor/1"
E2E_ENGINE_CONTRACTS = (
    "engine.polynomial.factor/1",
    "engine.polynomial.definite-integral/1",
    "engine.matrix.inverse/1",
)


def engine_plan(contract_id: str) -> CheckPlanProposal:
    spec = engine_contract(contract_id)
    assert spec is not None
    kernel = spec.generator
    return CheckPlanProposal(
        contract_id=contract_id,
        reason="The request names a supported bounded mathematics check.",
        goal=KernelGoal(
            operation=kernel.operation,
            answer_type=kernel.answer_type,
            min_degree=kernel.min_degree,
            max_degree=kernel.max_degree,
            max_abs_coefficient=kernel.max_abs_coefficient,
            min_dimension=kernel.min_dimension,
            max_dimension=kernel.max_dimension,
            requires_general_antiderivative=kernel.requires_general,
            domain_assumptions=list(kernel.domain_assumptions),
        ),
    )


def engine_template(contract_id: str) -> TemplateAuthorProposal:
    spec = engine_contract(contract_id)
    assert spec is not None
    return TemplateAuthorProposal(
        contract_id=contract_id,
        structured_family=family_for(spec.generator_contract_id),
    )


class EngineScriptedProvider:
    provider = "stub"
    model = "stub-structured-engine"

    def __init__(self, contract_id: str) -> None:
        self.contract_id = contract_id
        self.calls: list[str] = []

    def generation_settings(self):
        return {"mode": "scripted", "reasoning_effort": "none"}

    def generate(self, request):
        if request.prompt_version.startswith("check-planner"):
            self.calls.append("check-planner")
            return engine_plan(self.contract_id)
        if request.prompt_version.startswith("check-author"):
            self.calls.append("check-author")
            return kernel_check("unused")
        self.calls.append("template-author")
        return engine_template(self.contract_id)


def template_definition(
    scope: EngineContractScope, *, goal: KernelGoal
) -> PilotTemplateDefinition:
    return PilotTemplateDefinition(
        schema_version=TEMPLATE_SCHEMA_VERSION_V3,
        renderer_version=STRUCTURED_RENDERER_VERSION,
        scope=scope,
        contract_id=scope.contract_id,
        structured_family=family_for(scope.generator_contract_id),
        goal=goal,
    )


def test_catalogue_exposes_exactly_eleven_engine_and_eleven_kernel_contracts():
    descriptors = contract_catalogue()
    engine_ids = [
        item["contract_id"]
        for item in descriptors
        if item["contract_id"] in ENGINE_CONTRACT_IDS
    ]
    kernel_ids = [
        item["contract_id"]
        for item in descriptors
        if item["contract_id"] in KERNEL_CONTRACT_IDS
    ]
    assert len(engine_ids) == 11
    assert sorted(engine_ids) == sorted(ENGINE_CONTRACT_IDS)
    assert len(kernel_ids) == 11
    assert not set(engine_ids) & set(kernel_ids)
    for contract_id in ENGINE_CONTRACT_IDS:
        descriptor = next(
            item for item in descriptors if item["contract_id"] == contract_id
        )
        spec = engine_contract(contract_id)
        assert spec is not None
        assert descriptor["grader"] == "engine"
        assert descriptor["generator_contract_id"] == spec.generator_contract_id
        assert descriptor["engine_operation"] == spec.operation
        assert "requires_general" not in descriptor
        assert is_engine_contract(get_contract(contract_id))


def test_plan_resolution_selects_engine_contract_and_stores_engine_scope(
    tmp_path: Path,
):
    application = app(tmp_path)
    provider = EngineScriptedProvider(ENGINE)
    record = application.author_template(
        "owner",
        prompt="Author an engine-graded polynomial factor check",
        provider=provider,
    )

    assert record.status == "ready", record.findings
    assert record.check is not None
    assert record.check.scope["schema_version"] == "check-scope/4"
    assert record.check.scope["contract_id"] == ENGINE
    assert record.check.scope["grader"] == "engine"
    assert record.check.scope["generator_contract_id"] == "polynomial.factor/1"
    assert record.check.definition["schema_version"] == "engine-check/1"
    assert record.check.definition["grader"] == "engine"
    engine_scope = EngineContractScope.model_validate(record.check.scope)
    assert contract_for_scope(record.check.scope) is engine_contract(ENGINE)
    assert record.selection is not None
    assert record.selection.contract_id == ENGINE
    assert record.template is not None
    assert record.template["contract_id"] == ENGINE
    assert record.template["structured_family"]["contract_id"] == "polynomial.factor/1"
    # Only the planner and template roles are model-driven; the engine check is
    # developer-owned and never authored by a model.
    assert "check-author" not in provider.calls
    assert provider.calls == ["check-planner", "template-author"]
    assert application.get_check("owner", record.check.check_ref.check_id).scope == (
        engine_scope.model_dump(mode="json")
    )


def test_invalid_or_mismatched_engine_scope_is_rejected():
    scope = engine_contract(ENGINE).scope().model_dump(mode="json")
    assert contract_for_scope(scope) is not None

    wrong_grader = {**scope, "grader": "kernel"}
    assert contract_for_scope(wrong_grader) is None
    assert scope_applicability_findings(wrong_grader, engine_plan(ENGINE).goal)

    wrong_generator = {**scope, "generator_contract_id": "matrix.inverse/1"}
    assert contract_for_scope(wrong_generator) is None
    assert scope_applicability_findings(wrong_generator, engine_plan(ENGINE).goal)

    other_goal = engine_plan("engine.matrix.determinant/1").goal
    assert scope_applicability_findings(scope, other_goal)

    from edcraft_validator.application.check_pilot.contracts import (
        applicability_findings,
    )

    assert applicability_findings(engine_contract(ENGINE), other_goal)


def test_untrusted_engine_definition_is_rejected_by_storage(tmp_path: Path):
    application = app(tmp_path)
    record = application.author_template(
        "owner",
        prompt="Author an engine-graded polynomial factor check",
        provider=EngineScriptedProvider(ENGINE),
    )
    assert record.check is not None
    broken = record.check.model_copy(
        update={
            "definition": {
                **record.check.definition,
                "generator_contract_id": "matrix.inverse/1",
            }
        }
    )
    with pytest.raises(PilotConflict):
        PilotStore(tmp_path).save_check("another-owner", broken)


@pytest.mark.parametrize("contract_id", ENGINE_CONTRACT_IDS)
def test_every_engine_contract_accepts_the_kernel_oracle_and_rejects_wrongs(
    contract_id: str,
):
    spec = engine_contract(contract_id)
    assert spec is not None
    problem = copy.deepcopy(FAMILIES[spec.generator_contract_id][0])
    expected = kernel_expected_answer(spec.generator_contract_id, problem)

    correct = grade_answer(contract_id, problem, expected)
    assert correct.outcome == "correct", (contract_id, correct.reason)
    assert correct.passed
    assert correct.kernel_verdict == "accepted"

    for wrong in kernel_wrong_answers(spec.generator_contract_id, problem, expected):
        result = grade_answer(contract_id, problem, wrong)
        assert result.outcome == "incorrect", (
            contract_id,
            wrong,
            result.outcome,
            result.reason,
        )
        assert not result.passed
        assert result.failed
        assert result.kernel_verdict == "rejected"


@pytest.mark.parametrize("contract_id", E2E_ENGINE_CONTRACTS)
def test_engine_end_to_end_author_qualify_approve_generate(
    tmp_path: Path, contract_id: str
):
    application = app(tmp_path, max_examples=8)
    provider = EngineScriptedProvider(contract_id)

    record = application.author_template(
        "owner", prompt=f"Author {contract_id}", provider=provider
    )
    assert record.status == "ready", record.findings
    assert record.check is not None
    assert record.check.qualification.status == "passed"
    assert record.qualification is not None and record.qualification.status == "passed"
    assert record.approval == "unreviewed"
    spec = engine_contract(contract_id)
    assert spec is not None
    assert record.template is not None
    assert record.template["schema_version"] == "pilot-template/3"
    assert record.template["contract_id"] == contract_id
    assert record.template["scope"]["schema_version"] == "check-scope/4"
    assert record.template["scope"]["generator_contract_id"] == (
        spec.generator_contract_id
    )
    assert record.template["structured_family"]["contract_id"] == (
        spec.generator_contract_id
    )

    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=7, quantity=1)

    approved = application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    assert approved.approval == "approved"

    from edcraft_validator.application.check_pilot.structured import (
        family_assignment_count,
    )

    quantity = min(3, family_assignment_count(family_for(spec.generator_contract_id)))
    batch = application.generate("owner", record.template_id, seed=7, quantity=quantity)
    assert len(batch.questions) == quantity
    assert batch.shortfall == 0
    for question in batch.questions:
        assert question.grader == "engine"
        assert question.engine_outcome == "correct"
        assert question.kernel_verdict in {"accepted", "rejected"}
        assert question.check_ref == record.check.check_ref
        assert question.choices[question.correct_index] == question.answer


def test_agreement_proof_engine_and_kernel_grading_build_identical_questions(
    tmp_path: Path,
):
    """Same family and seed: only the grader differs, the items do not."""
    for contract_id in E2E_ENGINE_CONTRACTS:
        spec = engine_contract(contract_id)
        assert spec is not None
        goal = engine_plan(contract_id).goal
        assert isinstance(goal, KernelGoal)

        engine_definition = spec.definition()
        engine_template_definition = template_definition(spec.scope(), goal=goal)
        engine_batch = build_generation_batch(
            template_id="tpl_" + "a" * 24,
            seed=11,
            quantity=2,
            definition=engine_definition,
            template=engine_template_definition,
            check_ref=CheckRef(
                check_id="chk_" + "b" * 24, version="1", sha256="c" * 64
            ),
        )

        kernel_scope = spec.generator.scope()
        kernel_template_definition = PilotTemplateDefinition(
            schema_version=TEMPLATE_SCHEMA_VERSION_V3,
            renderer_version=STRUCTURED_RENDERER_VERSION,
            scope=kernel_scope,
            contract_id=spec.generator_contract_id,
            structured_family=family_for(spec.generator_contract_id),
            goal=goal,
        )
        kernel_batch = build_generation_batch(
            template_id="tpl_" + "a" * 24,
            seed=11,
            quantity=2,
            definition=structured_recipe(),
            template=kernel_template_definition,
            check_ref=CheckRef(
                check_id="chk_" + "b" * 24, version="1", sha256="c" * 64
            ),
        )

        assert [
            (item.question, item.expression, item.choices, item.correct_index)
            for item in engine_batch.questions
        ] == [
            (item.question, item.expression, item.choices, item.correct_index)
            for item in kernel_batch.questions
        ]
        assert len(engine_batch.questions) == 2
        assert all(item.grader == "engine" for item in engine_batch.questions)
        assert all(item.engine_outcome == "correct" for item in engine_batch.questions)
        assert all(item.grader == "kernel" for item in kernel_batch.questions)
        assert all(
            item.engine_outcome is None and item.kernel_verdict is None
            for item in kernel_batch.questions
        )


def test_kernel_graded_batch_does_not_carry_engine_evidence(tmp_path: Path):
    spec = kernel_contract("polynomial.factor/1")
    goal = kernel_plan("polynomial.factor/1").goal
    definition = PilotTemplateDefinition(
        schema_version=TEMPLATE_SCHEMA_VERSION_V3,
        renderer_version=STRUCTURED_RENDERER_VERSION,
        scope=spec.scope(),
        contract_id=spec.contract_id,
        structured_family=family_for(spec.contract_id),
        goal=goal,
    )
    batch = build_generation_batch(
        template_id="tpl_" + "d" * 24,
        seed=3,
        quantity=2,
        definition=structured_recipe(),
        template=definition,
        check_ref=CheckRef(check_id="chk_" + "e" * 24, version="1", sha256="f" * 64),
    )
    assert batch.questions
    for question in batch.questions:
        assert question.grader == "kernel"
        assert question.engine_outcome is None
        assert question.kernel_verdict is None


@pytest.mark.parametrize("outcome", ["unknown", "unsupported", "timeout", "error"])
def test_engine_refusals_fail_closed_and_keep_kernel_evidence(
    monkeypatch: pytest.MonkeyPatch, outcome: str
):
    from edcraft_validator.application.check_pilot import engine_checks

    def refuse(request: CorrectnessRequest) -> CorrectnessResult:
        return CorrectnessResult(
            outcome=outcome,
            reason=f"engine declined with {outcome}",
        )

    monkeypatch.setattr(engine_checks, "check_in_process", refuse)
    spec = engine_contract(ENGINE)
    assert spec is not None
    problem = copy.deepcopy(FAMILIES["polynomial.factor/1"][0])
    expected = kernel_expected_answer("polynomial.factor/1", problem)

    grading = engine_checks.grade_answer(ENGINE, problem, expected)
    assert grading.outcome == outcome
    assert not grading.passed
    assert not grading.failed
    assert grading.refused
    assert grading.kernel_verdict == "accepted"


def test_engine_adapter_gaps_name_the_contract_and_field():
    spec = engine_contract(ENGINE)
    assert spec is not None
    problem = copy.deepcopy(FAMILIES["polynomial.factor/1"][0])
    candidate = kernel_expected_answer("polynomial.factor/1", problem)
    broken = {key: value for key, value in candidate.items() if key != "expression"}
    with pytest.raises(EngineAdapterGap) as caught:
        to_correctness_request(ENGINE, problem, broken)
    assert caught.value.contract_id == ENGINE
    assert caught.value.field == "candidate.expression"

    grading = grade_answer(ENGINE, problem, broken, compare_kernel=False)
    assert grading.outcome == "unsupported"
    assert grading.refused
    assert any("candidate.expression" in item for item in grading.findings)


def test_antiderivative_form_gate_rejects_a_flipped_general_marker():
    problem = copy.deepcopy(FAMILIES["polynomial.antiderivative/1"][0])
    candidate = kernel_expected_answer("polynomial.antiderivative/1", problem)
    flipped = {**candidate, "general": not candidate["general"]}
    assert form_findings("engine.polynomial.antiderivative/1", problem, flipped)
    grading = grade_answer("engine.polynomial.antiderivative/1", problem, flipped)
    assert grading.outcome == "incorrect"


def test_engine_template_refusal_is_inconclusive_and_not_approvable(
    monkeypatch: pytest.MonkeyPatch,
):
    from edcraft_validator.application.check_pilot import worker

    spec = engine_contract(ENGINE)
    assert spec is not None
    goal = engine_plan(ENGINE).goal
    assert isinstance(goal, KernelGoal)
    definition = spec.definition()
    family = family_for(spec.generator_contract_id)

    def refuse(*args, **kwargs):
        raise worker._EngineRefusal("timeout", "engine ran out of budget")

    monkeypatch.setattr(worker, "grade_answer", refuse)
    qualification = worker._engine_template_qualification(
        definition=definition,
        family=family,
        scope=spec.scope(),
        goal=goal,
        config=PilotQualificationSettings(
            max_examples=4, max_execution_calls=100, timeout_seconds=30.0
        ),
        seed_value=5,
    )
    assert qualification.status == "inconclusive"
    assert any("timeout" in finding for finding in qualification.findings)


def test_engine_check_definition_records_the_generator_contract():
    spec = engine_contract(ENGINE)
    assert spec is not None
    definition = spec.definition()
    assert definition.contract_id == ENGINE
    assert definition.generator_contract_id == "polynomial.factor/1"
    assert definition.grader == "engine"


def test_small_settings_are_bounded():
    settings = small_settings()
    assert settings.max_examples <= 10
    assert settings.timeout_seconds <= 30
