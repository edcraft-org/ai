"""Isolated imports and injectable execution contracts, independent of test order."""

import asyncio
import subprocess
import sys
import threading

import pytest
from fastmcp import Client
from judge_helpers import TemplateJudge, candidate
from pydantic import ValidationError

from edcraft_validator.llm.decision import measure_relevance
from edcraft_validator.llm.forced_decision import ClassDecision
from edcraft_validator.llm.judge_configuration import load_judge_settings
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.server import create_validation_server


@pytest.mark.parametrize(
    "statement",
    [
        "from edcraft_validator.domains.domain_contract import DomainModule",
        "from edcraft_validator.application.template_workflow import "
        "TemplateApplication; TemplateApplication()",
        "from edcraft_validator.validation.check_contracts import ToolEvidence",
    ],
)
def test_contract_imports_do_not_start_a_server(statement):
    code = (
        statement
        + "; import sys; assert 'edcraft_validator.mcp.server' not in sys.modules; "
        "assert 'fastmcp' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


class ExternalDecision:
    provider, model = "custom", "custom-model"

    def __init__(self):
        self.last_usage = TokenUsage(input_tokens=10, output_tokens=1)
        self.closed = False

    def generation_settings(self):
        return {"reasoning_effort": "none"}

    def score(self, request, question):
        return 0.99

    def close(self):
        self.closed = True


async def test_external_provider_retains_usage_settings_and_cleanup():
    provider = ExternalDecision()
    report = await measure_relevance(
        "objective", "question", provider_factory=lambda: provider
    )
    assert report.status == "assessed" and provider.closed
    assert report.usage.model_call_count == 1 and report.usage.input_tokens == 10
    assert report.provider_settings == {"reasoning_effort": "none"}


async def test_unknown_usage_is_a_recorded_call_not_zero():
    provider = ExternalDecision()
    provider.last_usage = None
    report = await measure_relevance(
        "objective", "question", provider_factory=lambda: provider
    )
    assert report.usage.model_call_count == report.usage.unavailable_call_count == 1
    assert report.usage.input_tokens is None and report.usage.output_tokens is None


async def test_timeout_closes_transport_after_worker_finishes():
    release, closed = threading.Event(), threading.Event()

    class Slow(ExternalDecision):
        def score(self, request, question):
            assert release.wait(5)
            return 0.99

        def close(self):
            closed.set()

    try:
        report = await measure_relevance(
            "objective", "question", provider_factory=Slow, timeout_seconds=0.05
        )
        assert report.error_code == "RELEVANCE_TIMEOUT" and not closed.is_set()
        snapshot = report.model_dump_json()
    finally:
        release.set()
        assert await asyncio.to_thread(closed.wait, 2)
    assert report.model_dump_json() == snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {"EDCRAFT_JUDGE_REASONING_EFFORT": "none"},
        {"EDCRAFT_RELEVANCE_THRESHOLD": "nan"},
        {"EDCRAFT_RELEVANCE_THRESHOLD": "1.1"},
        {"EDCRAFT_JUDGE_MODEL": " "},
    ],
)
def test_invalid_settings_fail_at_boundary(changes):
    with pytest.raises(ValidationError):
        load_judge_settings(changes)


async def test_server_freezes_one_model_and_threshold_for_all_assessments(monkeypatch):
    from edcraft_validator.llm import judge_configuration

    seen = []

    class Model(TemplateJudge):
        def decide(self, messages, labels):
            self.last_usage = TokenUsage(input_tokens=7, output_tokens=1)
            return ClassDecision(
                label=labels[0],
                confidence=0.99,
                distribution={
                    label: 0.99 if i == 0 else 0.01 / (len(labels) - 1)
                    for i, label in enumerate(labels)
                },
            )

    def provider(selection):
        seen.append(selection.model)
        return Model()

    monkeypatch.setattr(judge_configuration, "create_model_provider", provider)
    monkeypatch.setenv("EDCRAFT_JUDGE_MODEL", "original")
    monkeypatch.setenv("EDCRAFT_RELEVANCE_THRESHOLD", "0.94")
    server = create_validation_server()
    monkeypatch.setenv("EDCRAFT_JUDGE_MODEL", "changed")
    monkeypatch.setenv("EDCRAFT_RELEVANCE_THRESHOLD", "0")
    async with Client(server) as client:
        difficulty = await client.call_tool(
            "code_assess_template_difficulty",
            {"candidate": candidate().model_dump(mode="json")},
        )
        relevance = await client.call_tool(
            "assess_relevance",
            {"request": {"author_request": "objective", "question_text": "question"}},
        )
        shared_relevance = await client.call_tool(
            "assess_template_relevance",
            {
                "author_request": "objective",
                "question_text": "question",
                "subject_sha256": "a" * 64,
            },
        )
        template_relevance = await client.call_tool(
            "code_assess_template_relevance",
            {
                "candidate": candidate().model_dump(mode="json"),
                "author_request": "objective",
            },
        )
    assert difficulty.structured_content["status"] == "passed"
    assert relevance.structured_content["decision"]["threshold"] == 0.94
    assert shared_relevance.structured_content["details"]["threshold"] == 0.94
    assert template_relevance.structured_content["status"] == "passed"
    assert template_relevance.structured_content["details"]["threshold"] == 0.94
    assert seen == ["original", "original", "original", "original"]


def test_classifier_prompt_is_independent_of_reasoning_wording(monkeypatch):
    from edcraft_validator.domains.code import template_difficulty
    from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric

    item, rubric = candidate(), load_code_difficulty_rubric()
    before = template_difficulty.build_template_decision_request(item, rubric)
    monkeypatch.setattr(
        template_difficulty, "REASONING_PROCEDURE", "Different reasoning instructions."
    )
    after = template_difficulty.build_template_decision_request(item, rubric)
    assert before == after
    assert (
        "Different reasoning instructions."
        in template_difficulty.build_template_difficulty_request(item, rubric).messages[
            0
        ]["content"]
    )
