"""Application permissions, full attempts and evidence-driven correction through MCP."""

import copy
import json
import uuid

import pytest
from test_template_evaluator import proposal

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.llm.llm_contracts import (
    CheckPlanResponse,
    ModelTurn,
    PlannedGenerationResponse,
    ToolCall,
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

    def __init__(self, proposals=None, plan=(SEMANTIC, STRUCTURE), call_factory=None):
        self.proposals = proposals or [proposal()]
        self.plan = plan
        self.generations = []
        self.turns = []
        self.call_factory = call_factory

    def generate(self, request):
        self.generations.append(copy.deepcopy(request.messages))
        current = self.proposals[
            min(len(self.generations) - 1, len(self.proposals) - 1)
        ]
        if not issubclass(request.response_model, PlannedGenerationResponse):
            return request.response_model.model_validate(current.model_dump())
        return PlannedGenerationResponse(
            proposal=current,
            checks=[{"name": name, "arguments": {}} for name in self.plan],
        )

    def tool_turn(self, messages, tools):
        self.turns.append(copy.deepcopy((messages, tools)))
        if not tools:
            # Evidence is actually delivered even after the last successful/failed call.
            assert any(message["role"] == "tool" for message in messages)
            return ModelTurn(content="Evidence received")
        names = [tool["function"]["name"] for tool in tools]
        for tool in tools:
            assert "candidate" not in tool["function"]["parameters"]["properties"]
            assert (
                "required_distractors"
                not in tool["function"]["parameters"]["properties"]
            )
        if self.call_factory:
            return self.call_factory(names)
        return calls(*names)


def calls(*names, arguments="{}"):
    return ModelTurn(
        calls=[
            ToolCall(id=str(uuid.uuid4()), name=name, arguments_json=arguments)
            for name in names
        ]
    )


def run(provider, client=None):
    client = client or RecordingClient(Executor())
    result = TemplateApplication(tool_client=client).author_template(
        REQUEST, domain=CodeDomain(), provider=provider
    )
    return result, client


def wrong_answer():
    return proposal().model_copy(update={"answer_expression": "a - b"})


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
    assert first.candidate_digest != second.candidate_digest
    assert len(executor.calls) == 2  # Finalization does not execute again.
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
    assert all(set(item) == {"tool", "error", "evidence"} for item in feedback)
    assert (
        result.artifact.authoring.attempts[0]["proposal"]["answer_expression"]
        == "a - b"
    )
    assert result.artifact.template.answer_expression is None
    assert [case.answer for case in result.artifact.validation.validated_cases] == [
        4,
        5,
        5,
        6,
    ]
    app = TemplateApplication()
    assert app.generate_question(result.artifact, domain=CodeDomain(), seed=42) == (
        app.generate_question(result.artifact, domain=CodeDomain(), seed=42)
    )
    assert len(executor.calls) == 2


def test_third_failure_returns_latest_proposal_full_history_and_never_attempt_four():
    provider = Provider([wrong_answer()])
    result, client = run(provider)
    assert result.status == "needs_review"
    assert result.artifact is None
    assert len(result.attempts) == len(provider.generations) == 3
    assert len(client.dispatches) == 6
    assert all(attempt.complete and not attempt.passed for attempt in result.attempts)
    assert result.proposal == result.attempts[-1].proposal
    assert provider.turns[-1][1] == []
    assert len(provider.generations[1]) == len(provider.generations[2])
    assert provider.generations[2][-2]["role"] == "assistant"
    feedback = json.loads(provider.generations[2][-1]["content"])["check_results"]
    assert feedback == [
        execution.model_feedback() for execution in result.attempts[1].executions
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        '{"candidate": {"code": "different program"}}',
        '{"required_distractors": 2}',
        "[]",
        '{"unknown": true}',
        "{invalid",
    ],
)
def test_invalid_or_overridden_arguments_never_dispatch_or_pass(arguments):
    result, client = run(
        Provider(
            plan=(SEMANTIC,),
            call_factory=lambda names: calls(SEMANTIC, arguments=arguments),
        )
    )
    assert result.status == "needs_review"
    assert client.dispatches == []
    assert len(result.attempts) == 3
    assert all(attempt.executions[0].error for attempt in result.attempts)


@pytest.mark.parametrize("tool", ["invented_tool", FEATURES])
def test_unknown_or_allowed_but_unselected_tool_never_dispatches(tool):
    result, client = run(
        Provider(plan=(SEMANTIC,), call_factory=lambda names: calls(tool))
    )
    assert result.status == "error"
    assert "conversation limit" in result.reason
    assert client.dispatches == []
    assert result.attempts[0].pending == [SEMANTIC]
    assert not result.attempts[0].complete


def test_duplicate_name_runs_once_and_cannot_pass():
    def repeat(names):
        return calls(SEMANTIC, SEMANTIC) if SEMANTIC in names else calls(STRUCTURE)

    result, client = run(Provider(call_factory=repeat))
    assert result.status == "needs_review"
    assert [name for name, _ in client.dispatches] == [SEMANTIC, STRUCTURE] * 3
    assert all(attempt.executions[1].error for attempt in result.attempts)


def test_missing_tool_calls_terminate_with_pending_checks():
    provider = Provider(
        call_factory=lambda names: ModelTurn(content="Everything passed")
    )
    result, client = run(provider)
    assert result.status == "error"
    assert len(provider.turns) == 6
    assert not result.attempts[0].complete
    assert not client.dispatches


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


def test_callable_schemas_do_not_expose_hidden_candidate_definitions():
    provider = Provider()
    result, _ = run(provider)
    assert result.status == "checked"
    for tool in provider.turns[0][1]:
        assert tool["function"]["parameters"] == {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
    # Full execution records and canonical answers remain available locally.
    execution = result.attempts[0].executions[0]
    assert execution.effective_arguments["candidate"] == result.attempts[0].candidate
    assert execution.evidence.details["canonical_answers"]


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


def test_model_argument_revision_keeps_membership_and_reruns_semantic_check():
    number = 0

    def request(names):
        nonlocal number
        number += 1
        # First attempt incorrectly requires a loop. Revision requests arithmetic.
        return ModelTurn(
            calls=[
                *calls(SEMANTIC).calls,
                *calls(
                    FEATURES,
                    arguments=json.dumps(
                        {"required": ["loop" if number == 1 else "arithmetic"]}
                    ),
                ).calls,
            ]
        )

    result, client = run(Provider(plan=(SEMANTIC, FEATURES), call_factory=request))
    assert result.status == "checked"
    assert len(result.attempts) == 2
    assert result.fixed_plan == [SEMANTIC, FEATURES]
    assert [name for name, _ in client.dispatches] == [SEMANTIC, FEATURES] * 2


def test_failed_final_feedback_preserves_third_failure_history():
    class NoReceipt(Provider):
        def tool_turn(self, messages, tools):
            if not tools:
                raise TimeoutError("Model unavailable for acknowledgement")
            return super().tool_turn(messages, tools)

    result, _ = run(NoReceipt([wrong_answer()]))
    assert result.status == "needs_review"
    assert len(result.attempts) == 3
    assert (
        result.feedback_error == "TimeoutError: Model unavailable for acknowledgement"
    )


def test_duplicate_call_ids_stop_before_dispatch():
    def duplicates(names):
        turn = calls(*names)
        turn.calls[1].id = turn.calls[0].id
        return turn

    result, client = run(Provider(call_factory=duplicates))
    assert result.status == "error"
    assert "Duplicate tool call ID" in result.reason
    assert not client.dispatches


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
