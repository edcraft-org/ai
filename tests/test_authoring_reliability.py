"""Wire formatting, bounded author recovery and coherent scoped revisions."""

import ast
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_authoring_loop import Executor, Provider, RecordingClient, run
from test_template_evaluator import proposal

from edcraft_validator.application.template_workflow import _generate_author
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.proposal_response import (
    CodeDistractorRevision,
    CodeProposalResponse,
)
from edcraft_validator.domains.code.template_revision import (
    author_difficulty_guidance,
    merge_revision,
    revision_contract,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding


def test_wire_lines_preserve_indentation_and_canonical_python_round_trip():
    value = proposal().model_dump(exclude={"answer_expression"}) | {
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
        CodeProposalResponse.model_validate(
            proposal().model_dump(exclude={"answer_expression"}) | {"code": lines}
        )


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


def test_real_wire_workflow_uses_partial_revision_and_preserves_valid_program():
    class WireAuthor(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []

        def generate(self, request):
            self.requests.append(request)
            payload = proposal().model_dump(exclude={"answer_expression"})
            if request.schema_name == "template_revision":
                assert request.response_model is CodeDistractorRevision
                return request.response_model.model_validate(
                    {key: payload[key] for key in ("parameters", "distractors")}
                )
            payload["distractors"] = [payload["distractors"][0]] * 3
            return request.response_model.model_validate(
                {
                    "proposal": payload,
                    "checks": [{"name": name, "arguments": {}} for name in self.plan],
                }
            )

    author = WireAuthor()
    result, _ = run(author)
    assert result.status == "checked" and len(result.attempts) == 2
    first, second = result.attempts
    for field in (
        "code",
        "entry_function",
        "question_template",
        "answer_target",
        "answer_expression",
    ):
        assert first.candidate[field] == second.candidate[field]
    assert first.candidate["distractors"] != second.candidate["distractors"]
    feedback = json.loads(author.requests[-1].messages[-1]["content"])
    assert feedback["revision_guidance"]["scope"] == "distractors_and_parameter_values"


def attempt_for(code):
    evidence = ToolEvidence(
        tool="code_validate_answers_and_distractors",
        version="test",
        status="failed",
        findings=[ToolFinding(code=code, message="Failure")],
    )
    return SimpleNamespace(
        executions=[SimpleNamespace(passed=False, error=None, evidence=evidence)]
    )


def test_distractor_patch_cannot_modify_code_interface_or_wording():
    current = CodeProposalResponse.model_validate(
        proposal().model_dump(exclude={"answer_expression"})
    )
    model, guidance = revision_contract(
        current, attempt_for("DISTRACTOR_SELECTION_FAILED")
    )
    assert model is CodeDistractorRevision
    assert guidance["scope"] == "distractors_and_parameter_values"
    assert set(model.model_fields) == {"parameters", "distractors"}
    payload = {name: current.model_dump()[name] for name in model.model_fields}
    payload["parameters"][0]["values"] = [5, 6]
    revised = merge_revision(current, model.model_validate(payload))
    assert revised.code == current.code
    assert revised.question_template == current.question_template
    assert revised.entry_function == current.entry_function
    assert revised.parameters[0].values == [5, 6]
    assert current.parameters[0].values == [1, 2]
    payload["parameters"][0]["name"] = "unexpected"
    with pytest.raises(GenerationSchemaError, match="names, kinds and order"):
        merge_revision(current, model.model_validate(payload))
    with pytest.raises(ValidationError):
        model.model_validate(payload | {"code": "different program"})


def test_difficulty_revision_retains_full_proposal_schema():
    current = CodeProposalResponse.model_validate(
        proposal().model_dump(exclude={"answer_expression"})
    )
    model, guidance = revision_contract(current, attempt_for("DIFFICULTY_MISMATCH"))
    assert model is CodeProposalResponse and guidance["scope"] == "proposal"
    assert "increasing repetition alone" in guidance["instructions"]


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
    assert result.usage.model_call_count == 4


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
