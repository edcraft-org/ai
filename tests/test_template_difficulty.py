"""Template-level judging and real MCP orchestration with scripted model calls."""

import json

import pytest
from fastmcp import Client
from pydantic import ValidationError
from test_authoring_loop import SEMANTIC, STRUCTURE, Executor, Provider
from test_difficulty_tool import ForbiddenExecutor, assessment
from test_template_evaluator import proposal

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.template_difficulty import (
    TEMPLATE_DIFFICULTY_TOOL,
    build_template_difficulty_request,
    template_assessment_model,
    template_sha256,
)
from edcraft_validator.llm.llm_contracts import CheckPlanResponse
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server


def candidate():
    return CodeDomain().build_candidate(
        CodeTemplateRequest(prompt="Create an addition question", difficulty="easy"),
        proposal(),
    )


class TemplateJudge:
    provider, model = "scripted", "template-judge"

    def __init__(self, estimate="easy", failure=None):
        self.estimate, self.failure = estimate, failure
        self.requests = []

    def generation_settings(self):
        return {"sampling": "scripted", "max_retries": 0}

    def generate(self, request):
        self.requests.append(request)
        self.last_usage = TokenUsage(input_tokens=100, output_tokens=50)
        if self.failure:
            raise self.failure
        value = assessment()
        options = value.pop("option_evidence")
        value.update(
            estimated_difficulty=self.estimate,
            domain_variation="All listed inputs need the same short reasoning.",
            unable_to_assess_reason="Essential code missing."
            if self.estimate is None
            else None,
            distractor_evidence={
                f"D{i}": {k: v for k, v in options[0].items() if k != "option_id"}
                for i in range(
                    1,
                    len(
                        json.loads(request.messages[1]["content"])["template"][
                            "distractors"
                        ]
                    )
                    + 1,
                )
            },
        )
        return request.response_model.model_validate(value)


async def test_template_tool_gets_full_domain_without_correctness_execution():
    judge = TemplateJudge()
    server = create_validation_server(
        difficulty_provider_factory=lambda: judge,
        code_execution_tool=ForbiddenExecutor(),
    )
    original = candidate()
    async with Client(server) as client:
        result = await client.call_tool(
            TEMPLATE_DIFFICULTY_TOOL, {"candidate": original.model_dump(mode="json")}
        )
    evidence = result.structured_content
    assert evidence["status"] == "passed"
    assert evidence["details"]["advisory"] is True
    assert evidence["details"]["template_sha256"] == template_sha256(original)
    assert evidence["details"]["usage"]["model_call_count"] == 1
    payload = json.loads(judge.requests[0].messages[1]["content"])
    assert payload == {
        "template": original.model_dump(
            mode="json", exclude={"template_id", "difficulty", "topic"}
        )
    }
    assert "inputs" not in payload["template"]
    assert "equally likely" in judge.requests[0].messages[0]["content"]
    other = original.model_copy(update={"difficulty": "hard", "template_id": "hard"})
    assert (
        build_template_difficulty_request(other, load_code_difficulty_rubric())
        == judge.requests[0]
    )


@pytest.mark.parametrize("count", range(2, 9))
def test_each_distractor_recipe_has_a_required_closed_evidence_key(count):
    schema = template_assessment_model(count).model_json_schema()
    evidence = schema["$defs"][f"EvidenceFor{count}DistractorRecipes"]
    assert evidence["required"] == [f"D{i}" for i in range(1, count + 1)]
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
    with pytest.raises(ValidationError):
        template_assessment_model(count).model_validate({})


def run(estimates, failure=None, *, validation=False, proposals=None):
    judges = []
    pending = iter(estimates)

    def factory():
        judge = TemplateJudge(next(pending), failure=failure)
        judges.append(judge)
        return judge

    class Author(Provider):
        def generate(self, request):
            if request.response_model is CheckPlanResponse:
                self.generations.append(request.messages)
                return CheckPlanResponse(
                    checks=[{"name": name, "arguments": {}} for name in self.plan]
                )
            return super().generate(request)

    author = Author(
        proposals=proposals, plan=(SEMANTIC, STRUCTURE, TEMPLATE_DIFFICULTY_TOOL)
    )
    server = create_validation_server(
        difficulty_provider_factory=factory, code_execution_tool=Executor()
    )
    app = TemplateApplication(tool_client=FastMcpToolClient(server))
    if validation:
        result = app.validate_template(
            candidate(), domain=CodeDomain(), provider=author
        )
    else:
        result = app.author_template(
            CodeTemplateRequest(
                prompt="Create an addition question", difficulty="easy"
            ),
            domain=CodeDomain(),
            provider=author,
        )
    return result, author, judges


def test_native_template_tool_feedback_reaches_author_and_third_revision_can_pass():
    result, author, judges = run(["hard", "medium", "medium", "easy"])
    assert result.status == "checked" and len(result.attempts) == 4
    assert len(judges) == 4 and all(len(j.requests) == 1 for j in judges)
    assert all(attempt.candidate["difficulty"] == "easy" for attempt in result.attempts)
    assert result.fixed_plan == [SEMANTIC, STRUCTURE, TEMPLATE_DIFFICULTY_TOOL]
    for request, attempt in zip(author.generations[1:], result.attempts, strict=False):
        feedback = json.loads(request[-1]["content"])["check_results"]
        difficulty = next(f for f in feedback if f["tool"] == TEMPLATE_DIFFICULTY_TOOL)
        assert (
            difficulty["evidence"]["details"] == attempt.executions[-1].evidence.details
        )
        assert difficulty["evidence"]["findings"][0]["code"] == "DIFFICULTY_MISMATCH"
    assert TEMPLATE_DIFFICULTY_TOOL in {
        item.check for item in result.artifact.validation.evidence
    }
    final_check = result.attempts[-1].executions[-1]
    assert final_check.evidence.details["template_sha256"] == template_sha256(
        result.artifact.template
    )
    assert final_check.application_arguments["candidate"] == (
        result.artifact.template.model_dump(mode="json")
    )
    assert len(result.attempts[-1].candidate["distractors"]) == 5
    assert len(final_check.application_arguments["candidate"]["distractors"]) == 3
    for attempt in result.attempts:
        assert attempt.executions[-1].requested_arguments == {}
    instance = TemplateApplication().generate_question(
        result.artifact, domain=CodeDomain(), seed=42
    )
    assert instance.question.proposed_answer in (4, 5, 6)
    assert len(judges) == 4  # Expansion makes no model calls.


@pytest.mark.parametrize(
    "failure",
    [GenerationResponseError, GenerationTransportError, GenerationTimeoutError],
)
def test_template_judge_failure_stops_without_check_retry_or_template_revision(failure):
    result, author, judges = run(["easy"], failure("private"))
    assert result.status == "needs_review" and result.artifact is None
    assert len(result.attempts) == len(author.generations) == len(judges) == 1
    output = result.attempts[0].executions[-1].evidence
    assert output.status == "error" and output.details["retryable"] is False
    assert "private" not in output.model_dump_json()


def test_correctness_failure_defers_difficulty_without_spending_a_judge_call():
    wrong = proposal().model_copy(update={"answer_expression": "a - b"})
    result, author, judges = run([], proposals=[wrong])
    assert result.status == "needs_review" and len(result.attempts) == 4
    assert len(author.generations) == 4 and judges == []
    assert all(a.pending == [TEMPLATE_DIFFICULTY_TOOL] for a in result.attempts)
    assert all(
        not any(e.tool == TEMPLATE_DIFFICULTY_TOOL for e in a.executions)
        for a in result.attempts
    )


def test_saved_artifact_rejects_difficulty_evidence_for_a_different_template():
    result, _, _ = run(["easy"])
    evidence = [e.evidence for e in result.attempts[0].executions]
    evidence[-1].details["template_sha256"] = "stale"
    with pytest.raises(ValueError, match="different template"):
        CodeDomain().finalize_checked_template(candidate(), evidence)


def test_missing_information_can_revise_the_template_without_repairing_the_judge():
    result, author, judges = run([None, "easy"])
    assert result.status == "checked" and len(author.generations) == len(judges) == 2
    assert all(len(j.requests) == 1 for j in judges)
    assert (
        result.attempts[0].executions[-1].evidence.findings[0].code
        == "DIFFICULTY_UNABLE_TO_ASSESS"
    )


def test_validation_runs_once_without_revising_difficulty_mismatch():
    result, author, judges = run(["hard"], validation=True)
    assert result.status == "needs_review" and result.artifact is None
    assert len(result.attempts) == len(author.generations) == len(judges) == 1


def test_unresolved_mismatch_retains_all_four_template_attempts():
    result, _, judges = run(["hard"] * 4)
    assert result.status == "needs_review" and result.artifact is None
    assert len(result.attempts) == len(judges) == 4


@pytest.mark.parametrize("limit", [-1, 4, True, 1.5])
def test_template_revision_limit_is_bounded(limit):
    with pytest.raises(ValueError):
        TemplateApplication(max_correction_attempts=limit)
