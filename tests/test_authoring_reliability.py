"""Wire formatting, bounded author recovery and complete feedback-guided revisions."""

import ast
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_authoring_loop import Executor, Provider, RecordingClient, run
from test_template_difficulty import TemplateJudge
from test_template_evaluator import proposal

from edcraft_validator.application.template_workflow import _generate_author
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.proposal_response import (
    CodeProposalResponse,
)
from edcraft_validator.domains.code.template_difficulty import TEMPLATE_DIFFICULTY_TOOL
from edcraft_validator.domains.code.template_revision import (
    author_difficulty_guidance,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server


def test_wire_lines_preserve_indentation_and_canonical_python_round_trip():
    value = proposal().model_dump() | {
        "code": ["def add(a, b):", "    total = a + b", "    return total", ""]
    }
    result = CodeProposalResponse.model_validate(value)
    ast.parse(result.code)
    assert result.code == "\n".join(value["code"])
    assert json.loads(result.model_dump_json())["code"] == value["code"]
    candidate = CodeDomain().build_candidate(
        CodeTemplateRequest(prompt="Add", difficulty="easy"), result
    )
    assert isinstance(candidate.code, str) and candidate.code == result.code
    assert CodeProposalResponse.model_validate_json(result.model_dump_json()) == result
    assert (
        CodeProposalResponse.model_json_schema()["properties"]["code"]["type"]
        == "array"
    )


@pytest.mark.parametrize(
    "lines", [[], ["def f():\n    return 1"], ["x\r"], ["x"] * 161]
)
def test_wire_rejects_embedded_newlines_or_excessive_lines(lines):
    with pytest.raises(ValidationError):
        CodeProposalResponse.model_validate(proposal().model_dump() | {"code": lines})


def test_author_uses_original_level_definitions_without_more_examples():
    guidance = author_difficulty_guidance()
    rubric = load_code_difficulty_rubric()
    levels = rubric.text.split("| Level | Anchor description |", 1)[1].split(
        "Choose the closest worked anchor", 1
    )[0]
    for row in levels.splitlines():
        if row.startswith(("| `easy` |", "| `medium` |", "| `hard` |")):
            assert row in guidance
    assert "```python" not in guidance
    assert "uniformly" in guidance


@pytest.mark.parametrize("with_difficulty", [False, True])
@pytest.mark.parametrize("failure", ["distractors", "answer"])
def test_full_wire_revision_replaces_candidate_and_rechecks_every_field(
    with_difficulty,
    failure,
):
    replacement = {
        "code": ["def combine(x, y):", "    total = x + y", "    return total"],
        "entry_function": "combine",
        "parameters": [
            {"name": "x", "kind": "integer", "values": [2, 3]},
            {"name": "y", "kind": "integer", "values": [5, 6]},
        ],
        "question_template": "Trace the code: what does combine({x}, {y}) return?",
        "answer_target": "return_value",
        "answer_expression": "x + y",
        "distractors": [
            {"expression": expr, "reason_template": "Makes an arithmetic error."}
            for expr in ["x + y + 1", "x + y - 1", "x + y + 2"]
        ],
    }

    class WireAuthor(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []

        def generate(self, request):
            self.requests.append(request)
            if request.schema_name == "template_revision":
                assert request.response_model is CodeProposalResponse
                assert request.prompt_version.endswith("+full-candidate-v1")
                return request.response_model.model_validate(replacement)
            payload = proposal().model_dump()
            if failure == "distractors":
                payload["distractors"] = [payload["distractors"][0]] * 3
            else:
                payload["answer_expression"] = "a - b"
            return request.response_model.model_validate(
                {
                    "proposal": payload,
                    "checks": [{"name": name, "arguments": {}} for name in self.plan],
                }
            )

    author = WireAuthor()
    if with_difficulty:
        author.plan += (TEMPLATE_DIFFICULTY_TOOL,)
    judge = TemplateJudge()
    # Use the real isolated executor to check the changed program and parameters.
    client = FastMcpToolClient(
        create_validation_server(difficulty_provider_factory=lambda: judge)
    )
    result, _ = run(author, client)
    assert result.status == "checked", result.reason
    assert len(result.attempts) == 2
    first, second = result.attempts
    for field in [
        "code",
        "entry_function",
        "parameters",
        "question_template",
        "answer_expression",
    ]:
        assert first.candidate[field] != second.candidate[field]
    assert second.candidate["entry_function"] == "combine"
    assert first.candidate["difficulty"] == second.candidate["difficulty"] == "easy"
    assert result.artifact.template.entry_function == "combine"
    assert result.artifact.template.answer_expression == "x + y"
    assert len(result.artifact.template.distractors) == 3
    assert all(e.passed for e in second.executions)
    assert second.executions[0].evidence.details["examples_checked"] == 4
    assert result.revision_policy == "full-candidate-v1"
    assert result.usage.model_call_count == 2
    feedback = json.loads(author.requests[-1].messages[-1]["content"])
    assert feedback["latest_candidate"] == first.candidate
    assert feedback["author_request"] == result.request
    assert feedback["remaining_revisions"] == 3
    assert feedback["failed_attempt"] == 1
    assert len(judge.requests) == int(with_difficulty)
    if with_difficulty:
        skipped = first.executions[-1]
        assert skipped.skip_reason == "Prerequisite checks did not pass"
        assert skipped.evidence is None
        assert first.pending == [TEMPLATE_DIFFICULTY_TOOL]
        assert feedback["check_results"][-1]["skip_reason"] == skipped.skip_reason
        assert second.executions[-1].passed


@pytest.mark.parametrize("override", ["difficulty", "num_distractors", "checks"])
def test_complete_revision_schema_rejects_request_and_plan_overrides(override):
    payload = proposal().model_dump()
    with pytest.raises(ValidationError):
        CodeProposalResponse.model_validate(payload | {override: "changed"})


@pytest.mark.parametrize("kind", ["partial", "invalid_parameters"])
def test_application_revalidates_constructed_revisions_before_new_checks(kind):
    class InvalidRevision(Provider):
        def generate(self, request):
            if self.generations:
                if kind == "partial":
                    valid = CodeProposalResponse.model_validate(proposal().model_dump())
                    return CodeProposalResponse.model_construct(
                        parameters=valid.parameters,
                        distractors=valid.distractors,
                    )
                return CodeProposalResponse.model_validate(
                    proposal().model_dump()
                ).model_copy(update={"parameters": []})
            return super().generate(request)

    initial = CodeProposalResponse.model_validate(proposal().model_dump()).model_copy(
        update={"answer_expression": "a - b"}
    )
    result, client = run(InvalidRevision([initial]))
    assert result.status == "error"
    assert result.failure.code == "schema_validation"
    assert "Invalid complete revision" in result.reason
    assert len(result.attempts) == 1
    assert len(client.dispatches) == 2
    assert result.artifact is None
    assert result.attempts[0].candidate["answer_expression"] == "a - b"


@pytest.mark.parametrize(
    "failure", [GenerationTimeoutError, GenerationResponseError, GenerationSchemaError]
)
def test_nontransport_author_failure_is_not_retried(failure):
    requests = []

    def generate(request):
        requests.append(request)
        raise failure("Private")

    with pytest.raises(failure):
        _generate_author(SimpleNamespace(generate=generate), "request")
    assert requests == ["request"]


def test_author_transport_retry_preserves_request_and_is_bounded():
    calls = []

    def generate(request):
        calls.append(request)
        if len(calls) == 1:
            raise GenerationTransportError("Connection failed")
        return "ok"

    assert _generate_author(SimpleNamespace(generate=generate), "request") == "ok"
    assert calls == ["request", "request"]
    calls.clear()

    def unavailable(request):
        calls.append(request)
        raise GenerationTransportError("Connection failed")

    with pytest.raises(GenerationTransportError):
        _generate_author(SimpleNamespace(generate=unavailable), "request")
    assert len(calls) == 2


def test_recovered_author_call_is_counted_without_using_a_template_revision():
    class Intermittent(Provider):
        first = True

        def generate(self, request):
            if self.first:
                self.first = False
                raise GenerationTransportError("Connection failed")
            return super().generate(request)

    result, _ = run(Intermittent())
    assert result.status == "checked" and len(result.attempts) == 1
    assert [call.operation for call in result.model_calls[:2]] == ["generation"] * 2
    assert result.model_calls[0].error == "transport"
    assert result.usage.model_call_count == 2


@pytest.mark.parametrize("status", [400, 401, 403])
def test_permanent_http_author_failures_are_not_retried(status):
    calls = []

    def unavailable(request):
        calls.append(request)
        cause = RuntimeError("HTTP failure")
        cause.status_code = status
        raise GenerationTransportError("Transport") from cause

    with pytest.raises(GenerationTransportError):
        _generate_author(SimpleNamespace(generate=unavailable), "request")
    assert len(calls) == 1


def test_distractor_failure_exposes_counterexamples_without_extra_execution():
    repeated = proposal().model_copy(
        update={"distractors": [proposal().distractors[0]] * 3}
    )
    executor = Executor()
    result, _ = run(Provider([repeated]), RecordingClient(executor))
    output = result.attempts[0].executions[0].evidence
    diagnostics = output.details["distractor_diagnostics"]
    assert {row["recipe_id"] for row in diagnostics} == {"D1", "D2", "D3"}
    assert all(row["kind"] == "DISTRACTOR_EQUALS_ANSWER" for row in diagnostics)
    assert all(
        row["answer"] == row["inputs"]["a"] + row["inputs"]["b"] for row in diagnostics
    )
    assert len(executor.calls) == 4  # Once per attempt, not again for diagnostics.
