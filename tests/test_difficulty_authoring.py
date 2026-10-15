"""Correction belongs to the authoring application, not the assessment tool."""

import json

import pytest
from fastmcp import Client
from test_difficulty_tool import ForbiddenExecutor, Provider, assessment, question

from edcraft_validator.application.difficulty_authoring import (
    author_question_with_difficulty,
)
from edcraft_validator.domains.code.difficulty import CodeQuestionDraft
from edcraft_validator.llm.llm_errors import GenerationResponseError
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.server import create_validation_server


class Author:
    provider, model = "scripted", "author"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def generation_settings(self):
        return {"mode": "scripted"}

    def generate(self, request):
        self.requests.append(request)
        self.last_usage = TokenUsage(input_tokens=100, output_tokens=20)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        response = response | {
            "inputs": [
                {"name": key, "value": value}
                for key, value in response["inputs"].items()
            ]
        }
        return request.response_model.model_validate(response)


def revised_question():
    result = question().model_dump()
    result.update(
        code=(
            "def f(x):\n    total = 0\n    for i in range(x):\n"
            "        total += i\n    return total"
        ),
        question="What does f(3) return after the loop finishes?",
        options=[
            {"id": key, "value": value}
            for key, value in zip("ABCD", [0, 1, 3, 6], strict=True)
        ],
    )
    return result


async def run(author_responses, estimates, requested="medium"):
    author = Author(author_responses)
    judges = []
    pending = list(estimates)

    def judge_factory():
        estimate = pending.pop(0)
        value = assessment()
        value["estimated_difficulty"] = estimate
        if estimate is None:
            value["unable_to_assess_reason"] = "The required question body is missing."
        judge = Provider(value)
        judges.append(judge)
        return judge

    server = create_validation_server(
        difficulty_provider_factory=judge_factory,
        code_execution_tool=ForbiddenExecutor(),
    )
    async with Client(server) as client:
        result = await author_question_with_difficulty(
            "Create a loop-based Python tracing MCQ.",
            requested,
            provider_factory=lambda: author,
            tool_client=client,
        )
    return result, author, judges


async def test_initial_match_needs_no_correction():
    report, author, judges = await run([question().model_dump()], ["medium"])
    assert report.status == "matches"
    assert len(report.attempts) == len(author.requests) == len(judges) == 1
    assert report.attempts[0].question == question()


def test_authoring_schema_is_closed_and_draft_inputs_preserve_values():
    schema = CodeQuestionDraft.model_json_schema()
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
    value = question().model_dump() | {"inputs": [{"name": "x", "value": 3}]}
    assert CodeQuestionDraft.model_validate(value).to_question() == question()


async def test_mismatch_generates_one_correction_then_reassesses():
    original = question().model_dump()
    revised = revised_question()
    report, author, judges = await run([original, revised], ["easy", "medium"])
    assert report.status == "matches"
    assert len(report.attempts) == len(author.requests) == len(judges) == 2
    first, second = report.attempts
    assert first.operation == "generation" and second.operation == "correction"
    assert first.question.model_dump() == original
    assert second.question.model_dump() == revised
    assert first.tool_output.difficulty_match == "too_easy"
    assert second.tool_output.difficulty_match == "matches"
    assert first.question.sha256 != second.question.sha256
    feedback = json.loads(author.requests[1].messages[1]["content"])
    assert feedback["requested_difficulty"] == "medium"
    assert feedback["previous_question"] == original
    assert feedback["difficulty_feedback"] == first.tool_output.model_dump(mode="json")
    assert "confidence" not in feedback["difficulty_feedback"]["judge"]["assessment"]
    assert first.generation.model_calls[0].operation == "generation"
    assert second.generation.model_calls[0].operation == "revision"
    assert second.generation.usage.input_tokens == 100


@pytest.mark.parametrize(
    "estimate,expected",
    [("easy", "mismatch"), ("hard", "mismatch"), (None, "unable_to_assess")],
)
async def test_remaining_nonmatch_stops_after_three_corrections(estimate, expected):
    report, author, _ = await run(
        [question().model_dump(), *[revised_question() for _ in range(3)]],
        [estimate] * 4,
    )
    assert report.status == expected
    assert len(author.requests) == len(report.attempts) == 4


async def test_generation_failure_is_retained_without_judging():
    report, author, judges = await run(
        [GenerationResponseError("private") for _ in range(4)], []
    )
    assert report.status == "error"
    assert report.error_code == "AUTHOR_INVALID_RESPONSE"
    assert len(author.requests) == 4 and judges == []
    assert report.attempts[0].generation.usage.output_tokens == 20
    assert "private" not in report.model_dump_json()


async def test_failed_correction_preserves_original_and_feedback():
    report, author, judges = await run(
        [
            question().model_dump(),
            *[GenerationResponseError("private") for _ in range(3)],
        ],
        ["easy"],
    )
    assert report.status == "error" and len(author.requests) == 4
    assert len(judges) == 1
    assert report.attempts[0].tool_output.difficulty_match == "too_easy"
    assert report.attempts[1].question is None
    assert report.attempts[1].generation.error_code == "AUTHOR_INVALID_RESPONSE"


async def test_judge_failure_does_not_turn_into_a_question_revision():
    author = Author([question().model_dump()])
    server = create_validation_server(
        difficulty_provider_factory=lambda: Provider(GenerationResponseError("private"))
    )
    async with Client(server) as client:
        report = await author_question_with_difficulty(
            "Create a tracing MCQ.",
            "medium",
            provider_factory=lambda: author,
            tool_client=client,
        )
    assert report.status == "error" and report.error_code == "JUDGE_INVALID_RESPONSE"
    assert len(author.requests) == len(report.attempts) == 1
    assert report.attempts[0].question is not None
    assert report.attempts[0].tool_output.status == "error"
    assert len(report.attempts[0].tool_output.judge_attempts) == 4
