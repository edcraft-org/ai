"""Quality remains advisory even for similar, malformed or incorrect questions."""

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from edcraft_validator.application.code_relevance import (
    CodeRelevanceReview,
    review_code_question_relevance,
)
from edcraft_validator.domains.code.question_checks import (
    check_concrete_correctness,
    check_requirements,
)
from edcraft_validator.domains.code.relevance import (
    CodeQuestionRequest,
    relevance_input,
    rendered_question,
)
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.tools.python_execution import ExecutionResult
from tests.test_difficulty_tool import Provider, question


class Decisions:
    provider, model = "fake", "decision-test"

    def __init__(self, value=1.0):
        self.value = value
        self.texts = None

    def score(self, request_text, question_text):
        self.texts = [request_text, question_text]
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Executor:
    def __init__(self, result=None):
        self.result = result or ExecutionResult(ok=True, answer=10)
        self.calls = 0

    def execute_batch(self, *args, **kwargs):
        self.calls += 1
        return [self.result]


async def assess(*, item=None, request=None, decisions=None, **kwargs):
    return await review_code_question_relevance(
        item or question(),
        request or CodeQuestionRequest(prompt="Trace arithmetic."),
        decision_provider_factory=lambda: decisions or Decisions(),
        execution_tool=Executor(),
        **kwargs,
    )


async def test_full_content_and_independent_evidence_are_explicit():
    decisions = Decisions()
    report = await assess(decisions=decisions)
    data = json.loads(report.model_dump_json())
    assert report.status == "assessed" and report.advisory
    assert report.technical.status == "passed"
    assert report.relevance.decision.score == 1
    assert report.relevance.decision.duration_ms > 0
    assert data["version"] == "5.0.0"
    assert "difficulty_quality" not in data and "quality_concerns" not in data
    assert "judge" not in data and "relevance" in data
    assert "quality_score" not in data
    rendered = json.loads(decisions.texts[1])
    assert rendered == question().model_dump(mode="json", exclude={"correct_option"})
    assert decisions.texts == [
        report.relevance.decision.request_text,
        report.relevance.decision.question_text,
    ]


async def test_application_rejects_difficulty_report_input_without_decision():
    decisions = Decisions()
    with pytest.raises(TypeError, match="difficulty_report"):
        await assess(decisions=decisions, difficulty_report={"status": "error"})
    assert decisions.texts is None


async def test_report_rejects_attached_difficulty_evidence():
    report = await assess()
    data = report.model_dump(mode="json")
    data["difficulty_quality"] = {"status": "reused", "quality_concerns": []}
    with pytest.raises(ValueError, match="extra_forbidden"):
        CodeRelevanceReview.model_validate_json(json.dumps(data))


async def test_positive_decision_does_not_override_failures():
    item = question().model_copy(update={"correct_option": "A"})
    request = CodeQuestionRequest(
        prompt="Trace nested loops.",
        required_features=["nested_loop"],
        answer_target="loop_iterations",
        num_distractors=2,
    )
    report = await assess(item=item, request=request)
    assert report.status == "assessed"
    assert report.technical.status == "failed"
    assert report.technical.findings == [
        "CANONICAL_ANSWER_MISMATCH",
        "DISTRACTOR_EQUALS_ANSWER:C",
    ]
    assert report.requirements.status == "missing"
    assert set(report.requirements.findings) == {
        "MISSING_FEATURE:nested_loop",
        "ANSWER_TARGET_MISMATCH",
        "DISTRACTOR_COUNT_MISMATCH",
    }
    assert report.relevance.decision.score == 1


def test_keyword_and_unreachable_helper_cannot_satisfy_syntax_requirement():
    item = question().model_copy(
        update={
            "code": question().code
            + (
                "# nested loops\ndef unused(n):\n"
                "    for i in range(n):\n        for j in range(n):\n            pass\n"
            )
        }
    )
    result = check_requirements(
        item,
        CodeQuestionRequest(
            prompt="Use nested loops.", required_features=["nested_loop"]
        ),
    )
    assert result.status == "missing"
    assert "nested_loop" not in result.observed_features


@pytest.mark.parametrize(
    "change,finding",
    [
        ({"correct_option": "A"}, "CANONICAL_ANSWER_MISMATCH"),
        ({"code": "import os\ndef f(x): return x"}, "UNSUPPORTED_CODE"),
        ({"code": "not python!"}, "UNSUPPORTED_CODE"),
    ],
)
def test_correctness_and_supported_subset_are_hard_requirements(change, finding):
    result = check_concrete_correctness(
        question().model_copy(update=change), Executor(), 1
    )
    assert result.status == "failed" and finding in result.findings


def test_distinct_options_and_missing_trace_evidence_never_pass():
    item = question()
    item.options[1].value = item.options[0].value
    result = check_concrete_correctness(item, Executor(), 1)
    assert result.status == "failed" and "DUPLICATE_OPTION:B" in result.findings
    item.answer_target = "loop_iterations"
    result = check_concrete_correctness(item, Executor(), 1)
    assert result.status == "error" and result.findings == ["ANSWER_TARGET_UNAVAILABLE"]
    result = check_concrete_correctness(
        question(),
        Executor(ExecutionResult(ok=False, error_code="EXECUTION_TIMEOUT")),
        1,
    )
    assert result.status == "error"


@pytest.mark.parametrize(
    "target",
    ["loop_iterations", "loop_executions", "function_calls", "branch_executions"],
)
def test_counts_use_trace_summary_instead_of_return_value(target):
    item = question().model_copy(update={"answer_target": target})
    result = check_concrete_correctness(
        item,
        Executor(ExecutionResult(ok=True, answer=999, trace_summary={target: 10})),
        1,
    )
    assert result.status == "passed" and result.canonical_answer == 10


@pytest.mark.parametrize("difficulty_error", [False, True])
async def test_mcp_difficulty_success_or_failure_cannot_affect_relevance(
    difficulty_error,
):
    provider = Provider(
        RuntimeError("PRIVATE REMOTE ERROR") if difficulty_error else None
    )
    executor = Executor()
    server = create_validation_server(
        difficulty_provider_factory=lambda: provider,
        decision_provider_factory=Decisions,
        code_execution_tool=executor,
    )
    async with Client(server) as client:
        difficulty = await client.call_tool(
            "assess_code_difficulty", {"question": question().model_dump(mode="json")}
        )
        relevance = await client.call_tool(
            "assess_relevance",
            {
                "request": relevance_input(
                    question(), CodeQuestionRequest(prompt="Arithmetic")
                ).model_dump(mode="json"),
            },
        )
    assert len(provider.requests) == 1
    assert difficulty.structured_content["status"] == (
        "error" if difficulty_error else "assessed"
    )
    if not difficulty_error:
        assert difficulty.structured_content["judge"]["assessment"]["quality_concerns"]
    data = relevance.structured_content
    assert data["status"] == "assessed" and executor.calls == 0
    assert data["decision"]["relevant"] is True
    assert "difficulty_quality" not in data and "judge" not in data
    assert "PRIVATE REMOTE ERROR" not in json.dumps(data)


async def test_configuration_errors_are_explicit_and_do_not_leak_secrets():
    def broken():
        raise ValueError("PRIVATE TOKEN")

    report = await review_code_question_relevance(
        question(),
        CodeQuestionRequest(prompt="Arithmetic"),
        decision_provider_factory=broken,
        execution_tool=Executor(),
    )
    assert report.status == "error"
    assert report.technical.status == "passed"
    assert report.relevance.decision.error_code == "RELEVANCE_FAILED"
    assert "PRIVATE TOKEN" not in report.model_dump_json()


async def test_three_options_are_assessed_without_difficulty_evidence():
    item = question()
    item.options.pop()
    result = await assess(item=item)
    assert result.status == "assessed" and result.technical.status == "passed"
    assert len(json.loads(result.relevance.decision.question_text)["options"]) == 3


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
async def test_invalid_deadlines_fail_before_provider_calls(timeout):
    decisions = Decisions()
    with pytest.raises(ValueError, match="finite and positive"):
        await assess(decisions=decisions, relevance_timeout_seconds=timeout)
    assert decisions.texts is None
    with pytest.raises(ValueError, match="finite and positive"):
        create_validation_server(relevance_timeout_seconds=timeout)


async def test_mcp_tool_has_full_evidence_and_is_not_an_authoring_check():
    def forbidden():
        pytest.fail("Relevance assessment must not construct a difficulty judge")

    decisions, executor = Decisions(), Executor()
    server = create_validation_server(
        difficulty_provider_factory=forbidden,
        decision_provider_factory=lambda: decisions,
        code_execution_tool=executor,
    )
    async with Client(server) as client:
        tool = next(
            t for t in await client.list_tools() if t.name == "assess_relevance"
        )
        assert tool.model_dump(by_alias=True)["_meta"]["fastmcp"]["tags"] == [
            "capability:relevance"
        ]
        assert set(tool.input_schema["properties"]) == {"request"}
        assert "difficulty_quality" not in tool.output_schema["properties"]
        payload = relevance_input(
            question(), CodeQuestionRequest(prompt="Arithmetic")
        ).model_dump(mode="json")
        result = await client.call_tool("assess_relevance", {"request": payload})
        assert result.structured_content["status"] == "assessed"
        assert result.structured_content["version"] == "2.0.0"
        assert "technical" not in result.structured_content
        assert executor.calls == 0
        assert "difficulty_quality" not in result.structured_content
        assert "judge" not in result.structured_content
        decisions.texts = None
        executions = executor.calls
        with pytest.raises(ToolError):
            await client.call_tool(
                "assess_relevance",
                {
                    "request": payload,
                    "difficulty_report": {"status": "error"},
                },
            )
        assert decisions.texts is None and executor.calls == executions
        with pytest.raises(ToolError):
            await client.call_tool(
                "assess_relevance",
                {
                    "request": {**payload, "author_request": " "},
                },
            )
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("assess_code_quality", {})
        assert decisions.texts is None and executor.calls == 0


def test_rendering_preserves_all_learner_content_and_omits_the_designation():
    item = question()
    item.options.pop()
    content = json.loads(rendered_question(item))
    assert content["code"] == item.code
    assert len(content["options"]) == 3
    assert "correct_option" not in content
