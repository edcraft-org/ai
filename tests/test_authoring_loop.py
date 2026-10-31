"""Application permissions, full attempts and evidence-driven correction through MCP."""

import copy
import json

import pytest
from test_template_evaluator import proposal

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.llm.llm_contracts import (
    CheckPlanResponse,
    PlannedGenerationResponse,
)
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.tools.python_execution import ExecutionResult

SEMANTIC = "code_validate_answers_and_distractors"
STRUCTURE = "code_verify_template_structure"
FEATURES = "code_require_features"
REQUEST = CodeTemplateRequest(prompt="Create an addition question", difficulty="easy")


class Executor:
    def __init__(self):
        self.calls = []

    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        self.calls.append(code)
        return [
            ExecutionResult(ok=True, answer=item["a"] + item["b"]) for item in inputs
        ]


class RecordingClient(FastMcpToolClient):
    def __init__(self, executor):
        super().__init__(create_validation_server(code_execution_tool=executor))
        self.listings = 0
        self.dispatches = []

    def list_tools(self):
        self.listings += 1
        return super().list_tools()

    def call_tool(self, name, arguments, *, version=None):
        self.dispatches.append((name, copy.deepcopy(arguments)))
        return super().call_tool(name, arguments, version=version)


class Provider:
    provider = "scripted"
    model = "scripted-v1"

    def generation_settings(self):
        return {"mode": "scripted"}

    def __init__(self, proposals=None, plan=(SEMANTIC, STRUCTURE), plan_arguments=None):
        self.proposals = proposals or [proposal()]
        self.plan = plan
        self.generations = []
        self.turns = []
        self.plan_arguments = plan_arguments or {}

    def generate(self, request):
        self.generations.append(copy.deepcopy(request.messages))
        current = self.proposals[
            min(len(self.generations) - 1, len(self.proposals) - 1)
        ]
        if not issubclass(request.response_model, PlannedGenerationResponse):
            return request.response_model.model_validate(current.model_dump())
        return PlannedGenerationResponse(
            proposal=current,
            checks=[
                {"name": name, "arguments": self.plan_arguments.get(name, {})}
                for name in self.plan
            ],
        )

    def tool_turn(self, messages, tools):
        pytest.fail("Direct dispatch must not request native tools or acknowledgement")


def run(provider, client=None):
    client = client or RecordingClient(Executor())
    result = TemplateApplication(tool_client=client).author_template(
        REQUEST, domain=CodeDomain(), provider=provider
    )
    return result, client


def wrong_answer():
    return proposal().model_copy(update={"answer_expression": "a - b"})


def test_direct_checks_deliver_all_evidence_before_self_correction():
    plan = (SEMANTIC, STRUCTURE, FEATURES)
    arguments = {FEATURES: {"required": ["arithmetic"]}}
    provider = Provider([wrong_answer(), proposal()], plan, arguments)
    result, client = run(provider)
    assert result.status == "checked"
    assert [name for name, _ in client.dispatches] == list(plan) * 2
    assert len(result.attempts) == 2
    assert all(attempt.complete for attempt in result.attempts)
    assert not result.attempts[0].passed and result.attempts[1].passed
    assert [call.operation for call in result.model_calls] == ["generation", "revision"]
    revision = json.loads(provider.generations[1][-1]["content"])
    assert revision["check_results"] == [
        {**execution.model_feedback(), "model_arguments": execution.requested_arguments}
        for execution in result.attempts[0].executions
    ]
    assert revision["fixed_plan"] == list(plan)
    assert revision["check_plan"] == [check.model_dump() for check in result.check_plan]
    assert [
        args["required"] for name, args in client.dispatches if name == FEATURES
    ] == [["arithmetic"], ["arithmetic"]]


def test_application_runs_each_selected_check_once_without_provider_tool_support():
    class StructuredOnly:
        provider, model = "scripted", "structured-only"
        generate = Provider.generate

        def __init__(self):
            self.generations = []
            self.proposals = [proposal()]
            self.plan = (SEMANTIC, STRUCTURE)
            self.plan_arguments = {}

    result, client = run(StructuredOnly())
    assert result.status == "checked"
    assert [name for name, _ in client.dispatches] == [SEMANTIC, STRUCTURE]
    assert result.usage.model_call_count == 1
    assert result.feedback_error is None


def test_failure_runs_whole_plan_then_corrects_with_same_catalogue_and_fresh_evidence():
    provider = Provider([wrong_answer(), proposal()])
    executor = Executor()
    result, client = run(provider, RecordingClient(executor))
    assert result.status == "checked"
    assert client.listings == 1
    assert [name for name, _ in client.dispatches] == [SEMANTIC, STRUCTURE] * 2
    first, second = result.attempts
    assert first.complete and not first.passed
    assert second.complete and second.passed
    assert first.executions[0].evidence.findings[0].code == "PROPOSED_ANSWER_MISMATCH"
    assert first.executions[1].passed  # No fail-fast exit.
    assert first.candidate != second.candidate
    assert len(executor.calls) == sum(
        x.evidence.details.get("execution_calls", 0)
        for a in result.attempts
        for x in a.executions
        if x.evidence
    )  # Finalization does not execute again.
    assert not any(m["role"] == "tool" for m in provider.generations[1])
    revision = json.loads(provider.generations[1][-1]["content"])
    assert revision["fixed_plan"] == list(provider.plan)
    feedback = revision["check_results"]
    assert feedback[0]["evidence"]["status"] == "failed"
    assert feedback[1]["evidence"]["status"] == "passed"
    assert feedback[0]["evidence"]["details"] == (first.executions[0].evidence.details)
    assert feedback[0]["evidence"]["findings"][0]["code"] == (
        "PROPOSED_ANSWER_MISMATCH"
    )
    assert "details" not in feedback[1]["evidence"]
    assert all(
        set(item) == {"tool", "error", "evidence", "model_arguments"}
        for item in feedback
    )
    assert feedback[0]["model_arguments"] == {}
    assert result.attempts[0].candidate["answer_expression"] == "a - b"
    assert result.artifact.template.answer_expression == "a + b"
    assert result.artifact.validation.examples_checked > 0


def test_fourth_failure_retains_full_history_without_attempt_five():
    provider = Provider([wrong_answer()])
    result, client = run(provider)
    assert result.status == "needs_review"
    assert result.artifact is None
    assert len(result.attempts) == len(provider.generations) == 4
    assert len(client.dispatches) == 8
    assert all(attempt.complete and not attempt.passed for attempt in result.attempts)
    assert result.attempts[-1].candidate["answer_expression"] == "a - b"
    assert result.usage.model_call_count == 4
    assert result.feedback_error is None
    assert [call.operation for call in result.model_calls] == ["generation"] + [
        "revision"
    ] * 3
    assert len(provider.generations[1]) == len(provider.generations[2])
    for number, messages in enumerate(provider.generations[1:], 1):
        revision = json.loads(messages[-1]["content"])
        assert revision["latest_candidate"] == result.attempts[number - 1].candidate
        assert revision["failed_attempt"] == number
        assert revision["remaining_revisions"] == 4 - number
    feedback = json.loads(provider.generations[2][-1]["content"])["check_results"]
    assert feedback == [
        {
            **execution.model_feedback(),
            "model_arguments": execution.requested_arguments,
        }
        for execution in result.attempts[1].executions
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {"candidate": {"code": "different program"}},
        {"required_distractors": 2},
        {"unknown": True},
        [],
        "{invalid",
    ],
)
def test_invalid_or_overridden_plan_arguments_stop_before_any_dispatch(arguments):
    result, client = run(Provider(plan_arguments={SEMANTIC: arguments}))
    assert result.status == "error"
    assert result.failure.code in {"schema_validation", "ValidationError"}
    assert not result.attempts
    assert not client.dispatches
    assert result.usage.model_call_count == 1


@pytest.mark.parametrize("tool", ["invented_tool", "another_domain_tool"])
def test_unknown_planned_tool_never_dispatches(tool):
    result, client = run(Provider(plan=(SEMANTIC, tool)))
    assert result.status == "error"
    assert "not offered" in result.reason
    assert client.dispatches == []
    assert not result.attempts


def test_duplicate_plan_names_fail_before_any_dispatch():
    result, client = run(Provider(plan=(SEMANTIC, SEMANTIC)))
    assert result.status == "error"
    assert "unique" in result.reason
    assert not result.attempts and not client.dispatches


def test_unselected_checks_are_not_added_by_application():
    result, client = run(Provider(plan=(SEMANTIC,)))
    assert result.status == "checked"
    assert [name for name, _ in client.dispatches] == [SEMANTIC]
    assert result.fixed_plan == [SEMANTIC]


def test_revision_schema_cannot_change_plan_after_failed_attempt():
    class ChangingProvider(Provider):
        def generate(self, request):
            if self.generations:
                assert "checks" not in request.response_model.model_fields
                assert request.schema_name == "template_revision"
                self.plan = (STRUCTURE,)  # Does not affect the application's plan.
            return super().generate(request)

    result, client = run(ChangingProvider([wrong_answer(), proposal()]))
    assert result.status == "checked"
    assert [name for name, _ in client.dispatches] == [SEMANTIC, STRUCTURE] * 2
    assert result.fixed_plan == [SEMANTIC, STRUCTURE]


def test_revision_cannot_return_another_combined_plan_response():
    class WrongRevision(Provider):
        def generate(self, request):
            if self.generations:
                return PlannedGenerationResponse(
                    proposal=proposal(), checks=[{"name": STRUCTURE, "arguments": {}}]
                )
            return super().generate(request)

    result, client = run(WrongRevision([wrong_answer()]))
    assert result.status == "error"
    assert "Revision must return only the proposal" in result.reason
    assert len(client.dispatches) == 2
    assert result.fixed_plan == [SEMANTIC, STRUCTURE]


@pytest.mark.parametrize(
    "kind", ["unavailable", "malformed", "identity", "version", "error"]
)
def test_bad_mcp_results_never_pass_and_do_not_skip_other_checks(kind):
    class BrokenClient(RecordingClient):
        def call_tool(self, name, arguments, *, version=None):
            if name != SEMANTIC:
                return super().call_tool(name, arguments, version=version)
            if kind == "unavailable":
                raise TimeoutError("Unavailable MCP tool")
            raw = super().call_tool(name, arguments, version=version)
            if kind == "malformed":
                return {"status": "passed"}
            if kind == "identity":
                raw["tool"] = STRUCTURE
            if kind == "version":
                raw["version"] = "wrong-version"
            if kind == "error":
                raw.update(
                    status="error",
                    findings=[{"code": "CHECK_TIMEOUT", "message": "Timed out"}],
                )
            return raw

    result, client = run(Provider(), BrokenClient(Executor()))
    assert result.status == "needs_review"
    assert all(
        not attempt.executions[0].passed and attempt.executions[1].passed
        for attempt in result.attempts
    )


def test_structure_only_success_cannot_fabricate_reusable_answers():
    result, _ = run(Provider(plan=(STRUCTURE,)))
    assert result.status == "needs_review"
    assert result.attempts[0].passed
    assert result.artifact is None
    assert "Missing execution-derived" in result.reason


def test_application_injects_exact_candidate_and_original_request_count():
    result, client = run(Provider(plan=(SEMANTIC,)))
    _, arguments = client.dispatches[0]
    assert arguments["candidate"] == result.attempts[0].candidate
    assert arguments["required_distractors"] == REQUEST.num_distractors
    assert result.status == "checked"


def test_execution_records_keep_model_arguments_separate_from_owned_bindings():
    result, _ = run(Provider())
    assert result.status == "checked"
    execution = result.attempts[0].executions[0]
    assert execution.application_arguments == {"required_distractors": 3}
    assert execution.requested_arguments == {}
    assert execution.evidence.details["examples_checked"] > 0
    assert [check.model_dump() for check in result.check_plan] == [
        {"name": SEMANTIC, "arguments": {}},
        {"name": STRUCTURE, "arguments": {}},
    ]


def test_live_workflow_assertions_cover_authoring_editing_and_replay():
    from live_provider_helpers import check_live_workflow

    class WorkflowProvider(Provider):
        def generate(self, request):
            if request.response_model is CheckPlanResponse:
                return CheckPlanResponse(checks=[{"name": SEMANTIC, "arguments": {}}])
            return super().generate(request)

    fixture = proposal().model_copy(deep=True)
    fixture.parameters[0].values = [2, 3]
    fixture.parameters[1].values = [4, 5]
    check_live_workflow(WorkflowProvider([fixture]), reviewed_inputs=True)


def test_revision_cannot_mutate_frozen_feature_arguments():
    class ChangingProvider(Provider):
        def generate(self, request):
            if self.generations:
                self.plan_arguments[FEATURES]["required"][:] = ["loop"]
            return super().generate(request)

    provider = ChangingProvider(
        [wrong_answer(), proposal()],
        plan=(SEMANTIC, FEATURES),
        plan_arguments={FEATURES: {"required": ["arithmetic"]}},
    )
    result, client = run(provider)
    assert result.status == "checked"
    assert len(result.attempts) == 2
    assert [
        args["required"] for name, args in client.dispatches if name == FEATURES
    ] == [["arithmetic"], ["arithmetic"]]
    assert result.check_plan[-1].arguments == {"required": ["arithmetic"]}


def test_execution_ids_are_application_owned_and_unique_across_attempts():
    result, _ = run(Provider([wrong_answer(), proposal()]))
    ids = [
        execution.call_id
        for attempt in result.attempts
        for execution in attempt.executions
    ]
    assert len(ids) == len(set(ids)) == 4


def test_passing_checks_from_different_attempts_cannot_be_combined():
    class AlternatingClient(RecordingClient):
        def call_tool(self, name, arguments, *, version=None):
            raw = super().call_tool(name, arguments, version=version)
            attempt = (len(self.dispatches) - 1) // 2 + 1
            failed_name = SEMANTIC if attempt != 2 else STRUCTURE
            if name == failed_name:
                raw.update(
                    status="failed",
                    findings=[
                        {
                            "code": "EXAMPLE_FAILURE",
                            "message": "This attempt did not pass",
                        }
                    ],
                )
            return raw

    result, _ = run(Provider(), AlternatingClient(Executor()))
    assert result.status == "needs_review"
    assert all(not attempt.passed for attempt in result.attempts)
    assert result.artifact is None


def test_revision_transport_failure_keeps_complete_previous_attempt():
    class FailedRevision(Provider):
        def generate(self, request):
            if self.generations:
                raise TimeoutError("Revision timed out")
            return super().generate(request)

    result, _ = run(FailedRevision([wrong_answer()]))
    assert result.status == "error"
    assert result.reason == "TimeoutError: Revision timed out"
    assert len(result.attempts) == 1
    assert result.attempts[0].complete
    assert len(result.attempts[0].executions) == 2


@pytest.mark.parametrize("revision", ["success", "timeout", "invalid_schema"])
def test_generation_timing_includes_successful_and_failed_corrections(
    monkeypatch, revision
):
    from types import SimpleNamespace

    from edcraft_validator.application import template_workflow
    from edcraft_validator.llm.llm_errors import GenerationTimeoutError

    clock = [0.0]
    monkeypatch.setattr(
        template_workflow, "time", SimpleNamespace(perf_counter=lambda: clock[0])
    )

    class TimedProvider(Provider):
        def generate(self, request):
            if self.generations:
                clock[0] += 7.0
                if revision == "timeout":
                    raise GenerationTimeoutError("Correction timed out")
                if revision == "invalid_schema":
                    return PlannedGenerationResponse(
                        proposal=proposal(),
                        checks=[{"name": SEMANTIC, "arguments": {}}],
                    )
            else:
                clock[0] += 1.0
            return super().generate(request)

    result, _ = run(TimedProvider([wrong_answer(), proposal()]))
    assert result.duration_ms == 8000
    assert result.generation_duration_ms == 8000
    if revision == "success":
        assert result.status == "checked"
        assert result.artifact.authoring.generation_duration_ms == 8000
        assert result.failure is None
    else:
        assert result.status == "error"
        assert result.failure.stage == "generation"
        assert result.failure.code == (
            "timeout" if revision == "timeout" else "schema_validation"
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"required": []},
        {"required": ["invented"]},
        {"required": [123]},
        {"required": ["loop"], "candidate": {}},
        {"required": ["loop"], "extra": True},
    ],
)
def test_invalid_feature_arguments_stop_before_checking(arguments):
    result, client = run(
        Provider(plan=(FEATURES,), plan_arguments={FEATURES: arguments})
    )
    assert result.status == "error"
    assert result.failure.code == "schema_validation"
    assert not result.attempts and not client.dispatches


def test_revision_keeps_original_request_when_caller_mutates_its_request():
    request = CodeTemplateRequest(
        prompt="Create an addition question", difficulty="easy", num_distractors=3
    )
    original = request.model_dump(mode="json")
    author = Provider([wrong_answer(), proposal()])
    client = RecordingClient(Executor())

    def change_caller_request(snapshot):
        request.prompt = "A different request"
        request.difficulty = "hard"
        request.num_distractors = 2

    result = TemplateApplication(tool_client=client).author_template(
        request,
        domain=CodeDomain(),
        provider=author,
        on_catalogue_resolved=change_caller_request,
    )
    assert result.status == "checked"
    assert result.request == original
    assert request.model_dump() != original
    assert all(attempt.candidate["difficulty"] == "easy" for attempt in result.attempts)
    assert result.artifact.template.difficulty == "easy"
    assert len(result.artifact.template.distractors) == 3
    assert [
        args["required_distractors"]
        for name, args in client.dispatches
        if name == SEMANTIC
    ] == [3, 3]
    feedback = json.loads(author.generations[-1][-1]["content"])
    assert feedback["author_request"] == original
    assert feedback["latest_candidate"] == result.attempts[0].candidate
    assert result.revision_policy == feedback["revision_policy"] == "full-candidate-v1"
