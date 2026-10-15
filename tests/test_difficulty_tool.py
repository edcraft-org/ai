"""Difficulty-only judging, blinded prompts and MCP failure records."""

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from edcraft_validator.application.code_difficulty import (
    assess_code_question_difficulty,
)
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    DifficultyAssessment,
    load_code_difficulty_rubric,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.llm.openai_compatible_provider import OpenAICompatibleProvider
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.server import create_validation_server


def question():
    return CodeDifficultyQuestion(
        code="def f(x):\n    y = x + 2\n    return y * 2\n",
        entry_function="f",
        inputs={"x": 3},
        question="What does f(3) return?",
        answer_target="return_value",
        options=[
            {"id": option_id, "value": value}
            for option_id, value in zip("ABCD", [6, 7, 10, 12], strict=True)
        ],
        correct_option="C",
    )


def assessment():
    return {
        "estimated_difficulty": "easy",
        "dimensions": {
            name: {"rating": "low", "reason": reason}
            for name, reason in {
                "execution_burden": "Two sequential calculations give 5 then 10.",
                "changing_state": "Only y is assigned before the return.",
                "conceptual_interaction": "Addition feeds multiplication directly.",
                "answer_discrimination": "Sequential evaluation distinguishes C.",
            }.items()
        },
        "reason": "A short direct trace needs little coordination.",
        "solution_reasoning": "x is 3, y becomes 5, and the return value is 10.",
        "concepts_and_dependencies": "Assignment, addition, then multiplication.",
        "shortcuts": "Substitution gives (3 + 2) * 2.",
        "nearest_anchor": "The easy arithmetic worked anchor.",
        "option_evidence": [
            {
                "option_id": option_id,
                "reasoning": reason,
                "hypothesised_error": None if option_id == "C" else reason,
                "shortcut_or_cue": None,
            }
            for option_id, reason in zip(
                "ABCD",
                [
                    "6 omits the addition.",
                    "7 applies multiplication before addition.",
                    "10 follows both assignments correctly.",
                    "12 uses an extra increment, a weak distractor hypothesis.",
                ],
                strict=True,
            )
        ],
        "alternative_levels": [],
        "uncertainty_reason": None,
        "quality_concerns": ["The 12 distractor has weak plausibility evidence."],
    }


class Provider:
    provider, model = "fake", "judge-test"

    def __init__(self, response=None):
        self.response = assessment() if response is None else response
        self.requests = []
        self.last_usage = TokenUsage()

    def generation_settings(self):
        return {"sampling": "scripted", "max_retries": 0}

    def generate(self, request):
        self.requests.append(request)
        self.last_usage = TokenUsage(input_tokens=123, output_tokens=45)
        if isinstance(self.response, Exception):
            raise self.response
        return request.response_model.model_validate(self.response)


class ForbiddenExecutor:
    def execute_batch(self, *args, **kwargs):
        raise AssertionError("Difficulty assessment must never execute code")


async def assess(provider=None, item=None, **kwargs):
    return await assess_code_question_difficulty(
        item or question(),
        provider_factory=lambda: provider or Provider(),
        **kwargs,
    )


async def test_mcp_assessment_does_not_execute_or_report_correctness():
    provider = Provider()
    server = create_validation_server(
        difficulty_provider_factory=lambda: provider,
        code_execution_tool=ForbiddenExecutor(),
    )
    original = question().model_dump(mode="json")
    async with Client(server) as client:
        response = await client.call_tool(
            "assess_code_difficulty",
            {"question": original, "requested_difficulty": "hard"},
        )
    report = response.structured_content
    assert not response.is_error
    assert report["status"] == "assessed" and report["advisory"] is True
    assert "passed" not in {report["status"], report["difficulty_match"]}
    assert "technical" not in report
    assert "execution_timeout_seconds" not in report
    assert report["difficulty_match"] == "too_easy"
    assert report["question_sha256"] == question().sha256
    assert report["requested_difficulty"] == "hard"
    judge = report["judge"]
    assert judge["assessment"]["estimated_difficulty"] == "easy"
    assert judge["provider"] == "fake" and judge["model"] == "judge-test"
    assert judge["provider_settings"] == {"sampling": "scripted", "max_retries": 0}
    assert judge["usage"]["input_tokens"] == 123
    assert judge["usage"]["output_tokens"] == 45
    assert judge["model_calls"][0]["operation"] == "judging"
    assert 0 < judge["duration_ms"] <= report["duration_ms"]
    assert report["rubric_version"] == "python-tracing-v0.2"
    assert report["assessment_conditions_version"] == "manual-tracing-v0.1"
    assert (
        report["rubric_sha256"]
        == hashlib.sha256(Path("docs/difficulty-rubric.md").read_bytes()).hexdigest()
    )
    assert original == question().model_dump(mode="json")


async def test_requested_level_never_reaches_judge_and_full_question_does():
    provider = Provider()
    easy = await assess(provider, requested_difficulty="easy")
    hard = await assess(provider, requested_difficulty="hard")
    assert easy.difficulty_match == "matches"
    assert hard.difficulty_match == "too_easy"
    first, second = provider.requests
    assert first.messages == second.messages
    assert easy.judge.request_sha256 == hard.judge.request_sha256
    assert first.tool_catalogue is None
    payload = json.loads(first.messages[1]["content"])
    assert payload["question"] == question().model_dump(mode="json")
    assert set(payload) == {"question"}
    assert "requested_difficulty" not in json.dumps(payload)
    assert "generator" not in json.dumps(payload)
    assert load_code_difficulty_rubric().text in first.messages[0]["content"]
    assert "untrusted" in first.messages[0]["content"]
    assert "Never obey" in first.messages[0]["content"]
    assert "semantic prerequisites" in first.messages[0]["content"]
    assert "Do not execute code, verify correctness" in first.messages[0]["content"]
    assert "not execution-verified evidence" in first.messages[0]["content"]


async def test_no_requested_level_means_no_match_decision():
    report = await assess()
    assert report.status == "assessed"
    assert report.requested_difficulty is None and report.difficulty_match is None


@pytest.mark.parametrize(
    "target",
    [
        "return_value",
        "branch_executions",
        "loop_iterations",
        "loop_executions",
        "function_calls",
    ],
)
async def test_each_answer_target_is_forwarded_without_execution(target):
    # Forward exact MCQ content, keeping reference ratings out of the fake judge.
    data = json.loads(
        Path("reference_sets/python_tracing/dataset.json").read_text()
    )
    raw = next(q for q in data["questions"] if q["answer_target"] == target)
    item = CodeDifficultyQuestion.model_validate(
        {name: raw[name] for name in CodeDifficultyQuestion.model_fields}
    )
    async with Client(
        create_validation_server(
            difficulty_provider_factory=Provider,
            code_execution_tool=ForbiddenExecutor(),
        )
    ) as client:
        result = await client.call_tool(
            "assess_code_difficulty", {"question": item.model_dump(mode="json")}
        )
    report = result.structured_content
    assert report["status"] == "assessed"
    assert "technical" not in report


async def test_three_options_are_assessed_without_synthesising_a_fourth():
    item = question().model_copy(update={"options": question().options[:3]})
    proposed = assessment()
    proposed["option_evidence"].pop()
    provider = Provider(proposed)
    report = await assess(provider, item=item)
    assert report.status == "assessed"
    payload = json.loads(provider.requests[0].messages[1]["content"])
    assert len(payload["question"]["options"]) == 3


async def test_missing_usage_is_unknown_and_concurrent_calls_are_isolated():
    providers = []

    class Unmetered(Provider):
        def generate(self, request):
            result = super().generate(request)
            del self.last_usage
            return result

    def factory():
        provider = Unmetered()
        providers.append(provider)
        return provider

    reports = await asyncio.gather(
        *[
            assess_code_question_difficulty(question(), provider_factory=factory)
            for _ in range(2)
        ]
    )
    assert len(providers) == 2 and providers[0] is not providers[1]
    for report in reports:
        assert report.status == "assessed"
        assert report.judge.usage.model_call_count == 1
        assert report.judge.usage.input_tokens is None
        assert report.judge.model_calls[0].usage_unavailable_reason


async def test_missing_rubric_prevents_model_call(monkeypatch):
    from edcraft_validator.application import code_difficulty

    def unavailable():
        raise FileNotFoundError("private path")

    monkeypatch.setattr(code_difficulty, "load_code_difficulty_rubric", unavailable)
    provider = Provider()
    report = await assess(provider)
    assert report.status == "error" and report.error_code == "RUBRIC_UNAVAILABLE"
    assert report.judge is None and provider.requests == []
    assert "private path" not in report.model_dump_json()


@pytest.mark.parametrize(
    "estimate, alternatives, expected",
    [
        (None, [], "uncertain"),
        ("easy", ["medium"], "uncertain"),
        ("hard", ["medium"], "too_hard"),
    ],
)
async def test_uncertainty_is_retained(estimate, alternatives, expected):
    proposed = assessment()
    proposed.update(
        estimated_difficulty=estimate,
        alternative_levels=alternatives,
        uncertainty_reason="The closest anchor has material differences.",
    )
    report = await assess(Provider(proposed), requested_difficulty="easy")
    assert report.status == "assessed"
    assert report.difficulty_match == expected
    assert report.judge.assessment.estimated_difficulty == estimate


@pytest.mark.parametrize(
    "item_update",
    [
        {"code": "import os\ndef f(x):\n    return x\n"},
        {"code": "this is not valid Python!"},
        {"correct_option": "A"},
        {"inputs": {"x": 101}},
        {
            "options": [
                {"id": "A", "value": 10},
                {"id": "B", "value": 10},
                {"id": "C", "value": "ten"},
                {"id": "D", "value": True},
            ]
        },
    ],
)
async def test_question_correctness_is_not_a_prerequisite(item_update):
    provider = Provider()
    raw = question().model_dump(mode="json") | item_update
    async with Client(
        create_validation_server(
            difficulty_provider_factory=lambda: provider,
            code_execution_tool=ForbiddenExecutor(),
        )
    ) as client:
        result = await client.call_tool("assess_code_difficulty", {"question": raw})
    report = result.structured_content
    assert report["status"] == "assessed"
    assert "technical" not in report
    payload = json.loads(provider.requests[0].messages[1]["content"])
    assert payload == {"question": raw}


@pytest.mark.parametrize(
    "failure, expected",
    [
        (GenerationResponseError("secret response"), "JUDGE_INVALID_RESPONSE"),
        (GenerationTimeoutError("secret timeout"), "JUDGE_TIMEOUT"),
        (GenerationTransportError("secret url"), "JUDGE_TRANSPORT"),
        (RuntimeError("secret error"), "JUDGE_INTERNAL_ERROR"),
    ],
)
async def test_provider_failure_retains_usage_without_match_or_secret(
    failure, expected
):
    provider = Provider(failure)
    report = await assess(provider, requested_difficulty="easy")
    assert report.status == "error" and report.error_code == expected
    assert report.difficulty_match is None
    assert report.judge.assessment is None
    assert report.judge.usage.input_tokens == 123
    assert len(provider.requests) == 1
    assert "secret" not in report.model_dump_json()


async def test_actual_adapter_malformed_json_retains_tokens():
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=90, completion_tokens=15),
        choices=[SimpleNamespace(message=SimpleNamespace(content="{invalid"))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response))
    )
    provider = OpenAICompatibleProvider("openai", client, model="test")
    report = await assess(provider)
    assert report.status == "error"
    assert report.error_code == "JUDGE_INVALID_RESPONSE"
    assert report.judge.usage.input_tokens == 90
    assert report.judge.usage.output_tokens == 15


async def test_adapter_schema_failure_retains_findings_without_response_values():
    proposed = assessment()
    proposed.update(
        estimated_difficulty=None,
        uncertainty_reason=None,
        reason="PRIVATE_RESPONSE_CONTENT",
    )
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=90, completion_tokens=15),
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(proposed)))
        ],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response))
    )
    report = await assess(OpenAICompatibleProvider("openai", client, model="test"))
    assert report.error_code == "JUDGE_SCHEMA_VALIDATION"
    assert report.judge.validation_errors[0].code == "value_error"
    assert "uncertainty reason" in report.judge.validation_errors[0].message
    assert report.judge.usage.input_tokens == 90
    assert "PRIVATE_RESPONSE_CONTENT" not in report.model_dump_json()


@pytest.mark.parametrize(
    "problem", ["empty_reason", "no_uncertainty", "wrong_options", "legacy_confidence"]
)
async def test_invalid_judgments_cannot_become_matches(problem):
    proposed = assessment()
    if problem == "empty_reason":
        proposed["dimensions"]["changing_state"]["reason"] = "  "
    elif problem == "no_uncertainty":
        proposed["estimated_difficulty"] = None
    elif problem == "legacy_confidence":
        proposed["confidence"] = "high"
    else:
        proposed["option_evidence"].pop()
    report = await assess(Provider(proposed), requested_difficulty="easy")
    assert report.status == "error"
    assert report.difficulty_match is None
    assert report.judge.assessment is None
    assert report.judge.usage.output_tokens == 45
    if problem != "wrong_options":
        assert report.judge.validation_errors
        assert all(finding.code for finding in report.judge.validation_errors)


async def test_deadline_returns_snapshot_and_discards_late_result():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    class SlowProvider(Provider):
        def generate(self, request):
            started.set()
            try:
                release.wait(timeout=5)
                return super().generate(request)
            finally:
                finished.set()

    try:
        report = await assess(SlowProvider(), judge_timeout_seconds=0.1)
        assert started.is_set() and not finished.is_set()
        assert report.error_code == "JUDGE_TIMEOUT"
        assert report.judge.usage.model_call_count == 1
        assert report.judge.usage.input_tokens is None
        snapshot = report.model_dump_json()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert report.model_dump_json() == snapshot


async def test_unconfigured_provider_is_explicit_without_breaking_server(monkeypatch):
    monkeypatch.delenv("EDCRAFT_DIFFICULTY_PROVIDER", raising=False)
    async with Client(
        create_validation_server(code_execution_tool=ForbiddenExecutor())
    ) as client:
        report = await client.call_tool(
            "assess_code_difficulty", {"question": question().model_dump(mode="json")}
        )
    data = report.structured_content
    assert data["error_code"] == "JUDGE_CONFIGURATION_ERROR"
    assert "technical" not in data
    assert data["judge"]["usage"]["model_call_count"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_id",
        "missing_option_id",
        "nonfinite",
        "unknown_field",
        "empty_options",
    ],
)
async def test_invalid_mcp_input_shapes_fail_before_model_calls(change):
    value = question().model_dump(mode="json")
    if change == "duplicate_id":
        value["options"][0]["id"] = "B"
    elif change == "missing_option_id":
        value["options"].pop()
        value["correct_option"] = "D"
    elif change == "nonfinite":
        value["options"][0]["value"] = float("inf")
    elif change == "empty_options":
        value["options"] = []
    else:
        value["requested_difficulty"] = "hard"
    provider = Provider()
    async with Client(
        create_validation_server(difficulty_provider_factory=lambda: provider)
    ) as client:
        with pytest.raises(ToolError):
            await client.call_tool("assess_code_difficulty", {"question": value})
    assert provider.requests == []


def test_output_contract_is_compatible_with_strict_structured_generation():
    schema = DifficultyAssessment.model_json_schema()
    assert "confidence" not in schema["properties"]
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
    value = assessment()
    value["estimated_difficulty"] = "beginner"
    with pytest.raises(ValidationError):
        DifficultyAssessment.model_validate(value)


def test_packaged_rubric_resource_matches_source(monkeypatch, tmp_path):
    from edcraft_validator.domains.code import difficulty

    resource = tmp_path / "difficulty-rubric.md"
    resource.write_bytes(Path("docs/difficulty-rubric.md").read_bytes())
    monkeypatch.setattr(difficulty, "files", lambda package: tmp_path)
    assert (
        difficulty.load_code_difficulty_rubric().sha256
        == hashlib.sha256(resource.read_bytes()).hexdigest()
    )


def test_question_revision_changes_identity():
    original = question()
    edited = original.model_copy(update={"question": "Return value of f(3)?"})
    assert original.sha256 != edited.sha256
