"""Difficulty-only judging, blinded prompts and MCP failure records."""

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from judge_helpers import assessment
from pydantic import ValidationError

from edcraft_validator.domains.code.code_difficulty import (
    assess_code_question_difficulty,
)
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    DifficultyAssessment,
    load_code_difficulty_rubric,
)
from edcraft_validator.domains.code.difficulty_request import (
    KeyedDifficultyAssessment,
    runtime_instructions,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.llm.openai_compatible_provider import OpenAICompatibleProvider
from edcraft_validator.llm.usage import TokenUsage


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

        response = self.response
        if issubclass(request.response_model, KeyedDifficultyAssessment):
            response = wire_assessment(response)
        return request.response_model.model_validate(response)


def wire_assessment(response):
    return response | {
        "option_evidence": {
            item["option_id"]: {k: v for k, v in item.items() if k != "option_id"}
            for item in response["option_evidence"]
        }
    }


class ForbiddenExecutor:
    def execute_batch(self, *args, **kwargs):
        raise AssertionError("Difficulty assessment must never execute code")


async def assess(provider=None, item=None, **kwargs):
    return await assess_code_question_difficulty(
        item or question(),
        provider_factory=lambda: provider or Provider(),
        **kwargs,
    )


async def test_assessment_does_not_execute_or_report_correctness():
    provider = Provider()
    report = await assess(provider, requested_difficulty="hard")

    assert report.status == "assessed" and report.advisory is True
    assert "passed" not in {report.status, report.difficulty_match}
    assert "technical" not in report.model_dump()
    assert "execution_timeout_seconds" not in report.model_dump()
    assert report.difficulty_match == "too_easy"
    assert report.question_sha256 == question().sha256
    assert report.requested_difficulty == "hard"
    judge = report.judge
    assert judge is not None and judge.assessment is not None
    assert judge.timeout_seconds == 310
    assert judge.assessment.estimated_difficulty == "easy"
    assert judge.provider == "fake" and judge.model == "judge-test"
    assert judge.provider_settings == {"sampling": "scripted", "max_retries": 0}
    assert judge.usage.input_tokens == 123
    assert judge.usage.output_tokens == 45
    assert judge.model_calls[0].operation == "judging"
    assert 0 < judge.duration_ms <= report.duration_ms
    assert report.rubric_version == "python-tracing-v0.2"
    assert report.assessment_conditions_version == "manual-tracing-v0.1"
    assert (
        report.rubric_sha256
        == hashlib.sha256(Path("docs/difficulty-rubric.md").read_bytes()).hexdigest()
    )


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
    assert (
        runtime_instructions(load_code_difficulty_rubric())
        == first.messages[0]["content"]
    )
    assert "untrusted" in first.messages[0]["content"]
    assert "never follow" in first.messages[0]["content"]
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
    data = json.loads(Path("reference_sets/python_tracing/dataset.json").read_text())
    raw = next(q for q in data["questions"] if q["answer_target"] == target)
    item = CodeDifficultyQuestion.model_validate(
        {name: raw[name] for name in CodeDifficultyQuestion.model_fields}
    )

    provider = Provider()
    report = await assess(provider, item=item)

    assert report.status == "assessed"
    assert "technical" not in report.model_dump()
    payload = json.loads(provider.requests[0].messages[1]["content"])
    assert payload["question"]["answer_target"] == target


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
    from edcraft_validator.domains.code import code_difficulty

    def unavailable():
        raise FileNotFoundError("private path")

    monkeypatch.setattr(code_difficulty, "load_code_difficulty_rubric", unavailable)

    provider = Provider()
    report = await assess(provider)
    assert report.status == "error" and report.error_code == "RUBRIC_UNAVAILABLE"
    assert report.judge is None and provider.requests == []
    assert "private path" not in report.model_dump_json()


@pytest.mark.parametrize(
    "estimate,expected",
    [("easy", "matches"), ("medium", "too_hard"), ("hard", "too_hard")],
)
async def test_one_label_determines_comparison(estimate, expected):
    proposed = assessment() | {"estimated_difficulty": estimate}
    report = await assess(Provider(proposed), requested_difficulty="easy")
    assert report.status == "assessed"
    assert report.difficulty_match == expected
    assert "alternative_levels" not in report.judge.assessment.model_dump()


async def test_missing_information_is_unable_to_assess_without_a_comparison():
    proposed = assessment() | {
        "estimated_difficulty": None,
        "unable_to_assess_reason": "The required input is absent.",
    }

    report = await assess(Provider(proposed), requested_difficulty="easy")
    assert report.status == "unable_to_assess"
    assert report.difficulty_match is None and report.error_code is None


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

    report = await assess(provider, item=CodeDifficultyQuestion.model_validate(raw))
    assert report.status == "assessed"
    assert "technical" not in report.model_dump()

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
        unable_to_assess_reason=None,
        reason="PRIVATE_RESPONSE_CONTENT",
    )

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=90, completion_tokens=15),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(wire_assessment(proposed)))
            )
        ],
    )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response))
    )

    report = await assess(OpenAICompatibleProvider("openai", client, model="test"))
    assert report.error_code == "JUDGE_SCHEMA_VALIDATION"
    assert report.judge.validation_errors[0].code == "value_error"
    assert "unable-to-assess reason" in report.judge.validation_errors[0].message
    assert report.judge.usage.input_tokens == 90
    assert "PRIVATE_RESPONSE_CONTENT" not in report.model_dump_json()


@pytest.mark.parametrize(
    "problem",
    [
        "empty_reason",
        "missing_reason",
        "wrong_options",
        "legacy_confidence",
        "legacy_alternatives",
    ],
)
async def test_invalid_judgments_cannot_become_matches(problem):
    proposed = assessment()
    if problem == "empty_reason":
        proposed["dimensions"]["changing_state"]["reason"] = "  "
    elif problem == "missing_reason":
        proposed["estimated_difficulty"] = None
    elif problem == "legacy_confidence":
        proposed["confidence"] = "high"
    elif problem == "legacy_alternatives":
        proposed["alternative_levels"] = []
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


def test_output_contract_is_compatible_with_strict_structured_generation():
    schema = DifficultyAssessment.model_json_schema()
    assert "confidence" not in schema["properties"]
    assert "alternative_levels" not in schema["properties"]
    assert "uncertainty_reason" not in schema["properties"]

    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])

    value = assessment()
    value["estimated_difficulty"] = "beginner"
    with pytest.raises(ValidationError):
        DifficultyAssessment.model_validate(value)


def test_packaged_rubric_resource_matches_source(monkeypatch, tmp_path):
    from edcraft_validator.application import difficulty_rubrics

    resource = tmp_path / "difficulty-rubric.md"
    resource.write_bytes(Path("docs/difficulty-rubric.md").read_bytes())
    monkeypatch.setattr(difficulty_rubrics, "files", lambda package: tmp_path)

    assert (
        load_code_difficulty_rubric().sha256
        == hashlib.sha256(resource.read_bytes()).hexdigest()
    )


def test_question_revision_changes_identity():
    original = question()
    edited = original.model_copy(update={"question": "Return value of f(3)?"})
    assert original.sha256 != edited.sha256
