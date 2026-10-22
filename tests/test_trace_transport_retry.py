"""Unlimited opt-in deadlines, transport-excluded scoring and safe diagnostics."""

import json

from openai import OpenAI
from test_difficulty_tool import Provider, question
from test_trace_difficulty_evaluation import record

from edcraft_validator.domains.code.difficulty import (
    build_difficulty_request,
    load_code_difficulty_rubric,
)
from edcraft_validator.llm.judging import run_judge
from edcraft_validator.llm.llm_errors import GenerationTransportError
from scripts.evaluate_difficulty import (
    classification_metrics,
    safe_diagnostic,
)


async def test_none_explicitly_disables_the_judge_deadline():
    request = build_difficulty_request(question(), load_code_difficulty_rubric())
    report = await run_judge(request, provider_factory=Provider, timeout_seconds=None)
    assert report.status == "completed"
    assert report.timeout_seconds is None
    assert report.usage.model_call_count == 1


def test_none_disables_all_sdk_http_timeouts():
    with OpenAI(api_key="test-placeholder", timeout=None, max_retries=0) as client:
        assert client.timeout is None
        assert client._client.timeout.connect is None
        assert client._client.timeout.read is None
        assert client._client.timeout.write is None
        assert client._client.timeout.pool is None


def test_transport_is_excluded_but_invalid_content_remains_an_accuracy_failure():
    good = record("easy", "easy")
    transport = record("hard", None, error=True)
    malformed = record("medium", None, error=True)
    malformed["report"]["error_code"] = "JUDGE_INVALID_RESPONSE"
    result = classification_metrics([good, transport, malformed])
    assert result["assessment_slots"] == 3
    assert result["transport_excluded"] == 1
    assert result["scored"] == 2
    assert result["correct"] == 1
    assert result["accuracy"] == 0.5
    assert result["dimensions"]["changing_state"]["denominator"] == 2
    assert result["classes"]["medium"]["recall"] == 0


def test_all_transport_failures_mean_unavailable_accuracy():
    result = classification_metrics([record("hard", None, error=True)])
    assert result["scored"] == 0
    assert result["accuracy"] is None


def test_public_error_diagnostic_retains_status_but_redacts_credentials(monkeypatch):
    monkeypatch.setenv("SOCLAAS_API_KEY", "sensitive-test-key")
    cause = RuntimeError("upstream failure sensitive-test-key")
    cause.status_code = 504
    cause.request_id = "request-test"
    error = GenerationTransportError("transport")
    error.__cause__ = cause
    result = safe_diagnostic(error)
    assert result["http_status"] == 504
    assert result["request_id"] == "request-test"
    assert "sensitive-test-key" not in json.dumps(result)
    assert "[REDACTED]" in result["message"]
