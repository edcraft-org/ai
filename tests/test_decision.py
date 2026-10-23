"""Decision boundaries and failures without loading optional model libraries."""

import asyncio
import sys
import threading
from types import SimpleNamespace

import pytest

from edcraft_validator.llm import decision
from tests.test_code_relevance import Decisions, assess


@pytest.mark.parametrize(
    "score,expected",
    [(0.0, False), (decision.DEFAULT_RELEVANCE_THRESHOLD, True), (1.0, True)],
)
async def test_cutoff_is_inclusive_and_errors_are_not_negative_decisions(
    score, expected
):
    report = await assess(decisions=Decisions(score))
    assert report.status == "assessed"
    assert report.relevance.decision.relevant is expected
    assert report.relevance.decision.threshold == decision.DEFAULT_RELEVANCE_THRESHOLD


@pytest.mark.parametrize(
    "score", [None, True, "0.5", -0.1, 1.1, float("nan"), float("inf")]
)
async def test_invalid_scores_keep_other_checks_and_have_no_decision(score):
    report = await assess(decisions=Decisions(score))
    assert report.status == "error" and report.technical.status == "passed"
    assert report.relevance.decision.error_code == "RELEVANCE_FAILED"
    assert report.relevance.decision.score is None
    assert report.relevance.decision.relevant is None


@pytest.mark.parametrize(
    "error,code",
    [
        (OSError("PRIVATE PATH"), "RELEVANCE_CONFIGURATION_ERROR"),
        (ImportError("PRIVATE PATH"), "RELEVANCE_CONFIGURATION_ERROR"),
        (decision.InputTooLongError("PRIVATE TEXT"), "RELEVANCE_INPUT_TOO_LONG"),
    ],
)
async def test_configuration_and_length_errors_do_not_leak_details(error, code):
    report = await assess(decisions=Decisions(error))
    assert report.relevance.decision.error_code == code
    assert report.relevance.decision.relevant is None
    assert "PRIVATE" not in report.model_dump_json()


async def test_timeout_stays_an_error_after_worker_finishes():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    class Slow(Decisions):
        def score(self, request_text, question_text):
            started.set()
            try:
                assert release.wait(5)
                return 1.0
            finally:
                finished.set()

    try:
        result = await decision.measure_relevance(
            "request", "question", provider_factory=Slow, timeout_seconds=0.1
        )
        assert started.is_set()
        assert result.error_code == "RELEVANCE_TIMEOUT" and result.relevant is None
        snapshot = result.model_dump_json()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert snapshot == result.model_dump_json()


def test_model_limit_rejects_without_truncation_or_forward_pass(monkeypatch):
    class Tokenizer:
        def encode(self, text, *, add_special_tokens):
            assert "request" in text and "question" in text
            return list(range(4097))

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setattr(
        decision, "_load_runtime", lambda path: (None, Tokenizer(), None)
    )
    with pytest.raises(decision.InputTooLongError):
        decision.QwenDecisionProvider().score("request", "question")


def test_provider_construction_is_lazy_and_uses_local_path(monkeypatch):
    monkeypatch.setenv("EDCRAFT_RELEVANCE_MODEL_PATH", "/local/qwen")

    def forbidden(*args):
        pytest.fail("Constructing the server/provider must not load model weights")

    monkeypatch.setattr(decision, "_load_runtime", forbidden)
    provider = decision.QwenDecisionProvider()
    assert provider.path == "/local/qwen"
    assert provider.model == "Qwen/Qwen3-Reranker-0.6B"
