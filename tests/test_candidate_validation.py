"""The existing-candidate entry point uses the same MCP execution boundary."""

import json
from pathlib import Path

import pytest
from authoring_helpers import RequestPendingTools
from fastmcp import FastMCP
from pydantic import BaseModel

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.llm.llm_contracts import (
    CheckPlanResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.llm.llm_errors import GenerationSchemaError
from edcraft_validator.llm.tool_context import generation_messages
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.evidence import ToolEvidence
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.tools.python_execution import ExecutionResult

SEMANTIC = "code_validate_answers_and_distractors"
STRUCTURE = "code_verify_template_structure"


class Selector(RequestPendingTools):
    provider = "stub"
    model = "selector"

    def __init__(self, names):
        self.names = names
        self.requests = []
        self.transcripts = []

    def generate(self, request):
        self.requests.append(request)
        assert request.response_model is CheckPlanResponse
        return CheckPlanResponse.model_validate(
            {"checks": [{"name": name, "arguments": {}} for name in self.names]}
        )

    def tool_turn(self, messages, tools):
        self.transcripts.append(messages)
        return super().tool_turn(messages, tools)


class Executor:
    calls = 0

    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        self.calls += 1
        return [
            ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"]) for x in inputs
        ]


@pytest.fixture
def candidate():
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


def application(executor):
    return TemplateApplication(
        tool_client=FastMcpToolClient(
            create_validation_server(code_execution_tool=executor)
        )
    )


def test_model_selects_checks_for_exact_candidate_and_finalizes(candidate):
    original = candidate.model_copy(deep=True)
    executor = Executor()
    provider = Selector([SEMANTIC])
    app = application(executor)
    result = app.validate_template(candidate, domain=CodeDomain(), provider=provider)
    assert result.status == "checked", result.reason
    assert len(provider.requests) == 1
    assert candidate.model_dump_json() in provider.requests[0].messages[-1]["content"]
    assert provider.requests[0].tool_catalogue.names == CodeDomain.allowed_tool_names
    messages = generation_messages(provider.requests[0])
    assert "matching the supplied schema" in messages[1]["content"]
    assert "combined proposal" not in messages[1]["content"]
    assert result.request == {"candidate": original.model_dump(mode="json")}
    assert result.proposal == original.model_dump(mode="json")
    assert len(result.attempts) == 1
    assert result.attempts[0].executions[0].effective_arguments == {
        "candidate": original.model_dump(mode="json"),
        "required_distractors": 3,
    }
    assert result.artifact.template.template_id == original.template_id
    assert result.artifact.authoring.request == result.request
    assert result.artifact.validation.cases_validated == 8
    assert candidate == original
    assert executor.calls == 1
    first = app.generate_question(result.artifact, domain=CodeDomain(), seed=42)
    assert first == app.generate_question(result.artifact, domain=CodeDomain(), seed=42)
    assert executor.calls == 1
    assert len(provider.requests) == 1


def test_structure_only_plan_is_not_supplemented(candidate):
    executor = Executor()
    result = application(executor).validate_template(
        candidate, domain=CodeDomain(), provider=Selector([STRUCTURE])
    )
    assert result.status == "needs_review"
    assert result.artifact is None
    assert result.fixed_plan == [STRUCTURE]
    assert result.attempts[0].passed
    assert "Missing execution-derived canonical answers" in result.reason
    assert executor.calls == 0


def test_failed_candidate_is_not_rewritten_and_remaining_checks_run(candidate):
    candidate.answer_expression = "a + b + c"
    original = candidate.model_copy(deep=True)
    provider = Selector([SEMANTIC, STRUCTURE])
    executor = Executor()
    result = application(executor).validate_template(
        candidate, domain=CodeDomain(), provider=provider
    )
    assert result.status == "needs_review"
    assert result.artifact is None
    assert len(result.attempts) == 1
    assert len(provider.requests) == 1
    assert executor.calls == 1
    assert result.proposal == original.model_dump(mode="json")
    assert candidate == original
    executions = result.attempts[0].executions
    assert [x.tool for x in executions] == [SEMANTIC, STRUCTURE]
    assert [x.evidence.status for x in executions] == ["failed", "passed"]
    assert executions[0].evidence.findings[0].code == "PROPOSED_ANSWER_MISMATCH"
    tool_messages = [x for x in provider.transcripts[-1] if x["role"] == "tool"]
    assert len(tool_messages) == 2
    assert (
        json.loads(tool_messages[0]["content"])["evidence"]["findings"][0]["code"]
        == "PROPOSED_ANSWER_MISMATCH"
    )


def test_unknown_selected_tool_is_rejected_before_execution(candidate):
    executor = Executor()
    with pytest.raises(GenerationSchemaError, match="not offered"):
        application(executor).validate_template(
            candidate, domain=CodeDomain(), provider=Selector(["unknown"])
        )
    assert executor.calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"checks": []},
        {"checks": [{"name": STRUCTURE, "arguments": {}}] * 2},
        {"checks": [{"name": STRUCTURE, "arguments": {}}], "proposal": {}},
    ],
)
def test_candidate_plan_schema_rejects_empty_duplicate_or_rewritten_proposals(payload):
    with pytest.raises(ValueError):
        CheckPlanResponse.model_validate(payload)


@pytest.mark.parametrize("outcome", ["passed", "failed", "invalid_artifact"])
def test_existing_candidate_flow_is_domain_independent(outcome):
    class Candidate(BaseModel):
        value: int

    class Artifact(ValidatedTemplateArtifact):
        value: int

    server = FastMCP("example")

    @server.tool(description="Check a value", version="1")
    def positive(value: int) -> ToolEvidence:
        return ToolEvidence(
            tool="positive",
            version="1",
            status="failed" if outcome == "failed" else "passed",
            findings=[{"code": "NEGATIVE", "message": "negative"}]
            if outcome == "failed"
            else [],
        )

    class Domain:
        name = "example"
        candidate_model = Candidate
        allowed_tool_names = ("positive",)

        def validation_request(self, candidate):
            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": candidate.model_dump_json()}],
                response_model=CheckPlanResponse,
                prompt_version="example-v1",
            )

        def tool_bindings(self, request, candidate, tool_name):
            assert request is None
            return {"value": candidate.value}

        def finalize_checked_template(self, candidate, evidence):
            assert outcome != "failed", "Failed candidates must never be finalized"
            return (
                candidate
                if outcome == "invalid_artifact"
                else Artifact(value=candidate.value)
            )

    result = TemplateApplication(
        tool_client=FastMcpToolClient(server)
    ).validate_template(
        Candidate(value=7), domain=Domain(), provider=Selector(["positive"])
    )
    assert (
        result.status
        == {"passed": "checked", "failed": "needs_review", "invalid_artifact": "error"}[
            outcome
        ]
    )
    if outcome == "invalid_artifact":
        assert "shared validated artifact" in result.reason
    assert (result.artifact is not None) == (outcome == "passed")
