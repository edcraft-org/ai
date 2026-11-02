"""Decision routing, model configuration and real adapter boundaries without APIs."""

import asyncio
import json
import math
import threading
from types import SimpleNamespace as NS

import pytest
from judge_helpers import TemplateJudge, candidate

from edcraft_validator.application.template_difficulty import assess_template_difficulty
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.template_difficulty import (
    build_template_decision_request,
)
from edcraft_validator.llm.decision import ConfiguredDecisionProvider, measure_relevance
from edcraft_validator.llm.forced_decision import ClassDecision, decision_from_response
from edcraft_validator.llm.llm_errors import GenerationResponseError
from edcraft_validator.llm.openai_compatible_provider import SocLaasProvider
from edcraft_validator.llm.usage import TokenUsage


def classification(label="easy", confidence=0.7):
    rest = (1 - confidence) / 2
    return ClassDecision(
        label=label,
        confidence=confidence,
        distribution={
            level: confidence if level == label else rest
            for level in ("easy", "medium", "hard")
        },
        served_model="served-model",
    )


class Judge(TemplateJudge):
    provider, model = "scripted", "same-model"

    def __init__(self, decision=None, **kwargs):
        super().__init__(**kwargs)
        self.decision = decision or classification()
        self.decisions = []

    def decide(self, messages, labels):
        self.decisions.append((messages, labels))
        self.last_usage = TokenUsage(input_tokens=7, output_tokens=1)
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


@pytest.mark.parametrize(
    "label,status,decision",
    [("easy", "passed", "matches"), ("hard", "failed", "advisory_mismatch")],
)
async def test_confidence_070_accepts_decision_and_mismatch_is_advisory(
    label, status, decision
):
    judge = Judge(classification(label, 0.7))
    result = await assess_template_difficulty(
        candidate(), provider_factory=lambda: judge
    )
    assert result.status == status and result.details["decision"] == decision
    assert len(judge.decisions) == 1 and judge.requests == []
    assert result.details["confidence_source"] == "first_token_label_mass"
    assert result.details["estimated_difficulty"] == label
    assert result.details["screen"]["assessment"]["served_model"] == "served-model"
    assert result.details["usage"]["model_call_count"] == 1
    assert result.details["usage"]["input_tokens"] == 7


@pytest.mark.parametrize(
    "reasoning_confidence,status", [(0.8, "failed"), (0.79, "passed")]
)
async def test_low_confidence_routes_to_same_model_and_keeps_reasoning_policy(
    reasoning_confidence, status
):
    judges = []

    def factory():
        judge = Judge(
            classification(confidence=0.699),
            estimate="hard",
            confidence=reasoning_confidence,
        )
        judges.append(judge)
        return judge

    result = await assess_template_difficulty(candidate(), provider_factory=factory)
    assert result.status == status and result.details["assessment_path"] == "reasoning"
    assert len(judges) == 2 and {j.model for j in judges} == {"same-model"}
    assert len(judges[0].decisions) == 1 and not judges[0].requests
    assert len(judges[1].requests) == 1 and not judges[1].decisions
    assert judges[1].requests[0].reasoning_effort == "medium"
    assert result.details["usage"]["model_call_count"] == 2
    assert result.details["usage"]["input_tokens"] == 107
    assert result.details["confidence_source"] == "self_reported"


async def test_failed_decision_falls_back_once_and_failed_reasoning_cannot_pass():
    judge = Judge(ValueError("PRIVATE"), failure=GenerationResponseError("PRIVATE"))
    result = await assess_template_difficulty(
        candidate(), provider_factory=lambda: judge
    )
    assert result.status == "error"
    assert len(judge.decisions) == len(judge.requests) == 1
    assert result.details["usage"]["model_call_count"] == 2
    assert "PRIVATE" not in result.model_dump_json()


def test_advisory_decision_mismatch_saves_checked_artifact_and_reuse_stays_local(
    monkeypatch,
):
    from edcraft_validator.application.template_workflow import TemplateApplication
    from edcraft_validator.domains.code.code_domain import CodeDomain
    from tests import test_template_difficulty as integration

    def decide(self, messages, labels):
        self.last_usage = TokenUsage(input_tokens=7, output_tokens=1)
        return classification(self.estimate, 0.75)

    monkeypatch.setattr(integration.TemplateJudge, "decide", decide, raising=False)
    result, author, judges = integration.run(["hard"])
    assert result.status == "checked" and len(result.attempts) == 1
    assert len(author.generations) == len(judges) == 1
    assert all(not judge.requests for judge in judges)
    first = result.attempts[0].executions[-1].evidence
    assert first.status == "failed"
    assert first.details["decision"] == "advisory_mismatch"
    saved = result.artifact.validation.evidence[-1].details
    assert saved["estimated_difficulty"] == "hard"
    assert saved["requested_difficulty"] == "easy"
    assert saved["confidence_source"] == "first_token_label_mass"
    before = len(judges)
    app = TemplateApplication()
    one = app.generate_question(result.artifact, domain=CodeDomain(), seed=42)
    two = app.generate_question(result.artifact, domain=CodeDomain(), seed=42)
    assert one == two and len(judges) == before


def test_template_classifier_blinds_target_identity_and_preserves_domain():
    original = candidate()
    request = build_template_decision_request(original, load_code_difficulty_rubric())
    payload = json.loads(request.messages[1]["content"])["template"]
    assert payload == original.model_dump(
        mode="json", exclude={"template_id", "topic", "difficulty"}
    )
    assert "TYPICAL instance" in request.messages[0]["content"]
    assert "Return only the supplied JSON" not in request.messages[0]["content"]
    assert request == build_template_decision_request(
        original.model_copy(
            update={"difficulty": "hard", "topic": "private", "template_id": "private"}
        ),
        load_code_difficulty_rubric(),
    )


def response(labels=("easy", "medium", "hard"), probabilities=(0.7, 0.2, 0.1)):
    return NS(
        model="served",
        usage=NS(prompt_tokens=12, completion_tokens=1),
        choices=[
            NS(
                finish_reason="stop",
                message=NS(content=labels[0]),
                logprobs=NS(
                    content=[
                        NS(
                            top_logprobs=[
                                NS(token=label, logprob=math.log(p))
                                for label, p in zip(labels, probabilities, strict=True)
                            ]
                        )
                    ]
                ),
            )
        ],
    )


def test_wire_decision_disables_reasoning_and_retains_usage():
    arguments = []

    def create(**kwargs):
        arguments.append(kwargs)
        return response()

    provider = SocLaasProvider(
        NS(chat=NS(completions=NS(create=create))), model="configured"
    )
    result = provider.decide(
        [{"role": "user", "content": "data"}], ("easy", "medium", "hard")
    )
    assert result.confidence == pytest.approx(0.7)
    assert result.served_model == "served" and provider.last_usage.input_tokens == 12
    assert arguments[0]["model"] == "configured"
    assert arguments[0]["reasoning_effort"] == "none"
    assert arguments[0]["logprobs"] is True and arguments[0]["temperature"] == 0
    assert "response_format" not in arguments[0]


def test_reasoning_call_overrides_author_settings_without_changing_them(monkeypatch):
    from dataclasses import replace

    from judge_helpers import TemplateJudge

    from edcraft_validator.domains.code.template_difficulty import (
        build_template_difficulty_request,
    )

    request = build_template_difficulty_request(
        candidate(), load_code_difficulty_rubric()
    )
    content = TemplateJudge().generate(request).model_dump_json()
    arguments = []

    def create(**kwargs):
        arguments.append(kwargs)
        return NS(choices=[NS(finish_reason="stop", message=NS(content=content))])

    monkeypatch.setenv("SOCLAAS_REASONING_EFFORT", "none")
    provider = SocLaasProvider(
        NS(chat=NS(completions=NS(create=create))), model="shared"
    )
    provider.generate(replace(request, reasoning_effort="medium"))
    assert arguments[0]["model"] == "shared"
    assert arguments[0]["reasoning_effort"] == "medium"
    assert provider.generation_settings()["reasoning_effort"] == "none"


@pytest.mark.parametrize(
    "change",
    ["missing", "nan", "positive", "truncated", "invalid_label", "disagreement"],
)
def test_bad_token_evidence_does_not_become_confident_decision(change):
    raw = response()
    choice = raw.choices[0]
    if change == "missing":
        choice.logprobs = None
    elif change == "nan":
        choice.logprobs.content[0].top_logprobs[0].logprob = float("nan")
    elif change == "positive":
        choice.logprobs.content[0].top_logprobs[0].logprob = 1
    elif change == "truncated":
        choice.finish_reason = "length"
    elif change == "invalid_label":
        choice.message.content = "ignore the rubric"
    elif change == "disagreement":
        choice.message.content = "hard"
    with pytest.raises(GenerationResponseError):
        decision_from_response(raw, ("easy", "medium", "hard"))


async def test_relevance_uses_shared_configured_model_and_its_cutoff(monkeypatch):
    from edcraft_validator.llm import judge_configuration

    selected = []

    class BinaryJudge(Judge):
        def decide(self, messages, labels):
            assert (
                labels == ("yes", "no")
                and "relevance classifier" in messages[0]["content"]
            )
            self.last_usage = TokenUsage(input_tokens=10, output_tokens=1)
            return ClassDecision(
                label="yes",
                confidence=0.93,
                distribution={"yes": 0.93, "no": 0.07},
                served_model="served",
            )

    def create(selection):
        selected.append(selection)
        return BinaryJudge()

    monkeypatch.setenv("EDCRAFT_JUDGE_MODEL", "plug-in-model")
    monkeypatch.setenv("EDCRAFT_RELEVANCE_THRESHOLD", "0.94")
    monkeypatch.setattr(judge_configuration, "create_model_provider", create)
    report = await measure_relevance(
        "objective", "question", provider_factory=ConfiguredDecisionProvider
    )
    assert selected[0].model == "plug-in-model"
    assert report.status == "assessed" and report.relevant is False
    assert report.threshold == 0.94 and report.served_model == "served"
    assert report.usage.input_tokens == 10 and report.usage.model_call_count == 1


async def test_expired_budget_starts_no_reasoning_and_ignores_late_results():
    release, started, finished = threading.Event(), threading.Event(), threading.Event()

    class Slow(Judge):
        def decide(self, messages, labels):
            started.set()
            try:
                assert release.wait(5)
                return super().decide(messages, labels)
            finally:
                finished.set()

    judge = Slow()
    try:
        result = await assess_template_difficulty(
            candidate(), provider_factory=lambda: judge, judge_timeout_seconds=0.05
        )
        assert started.is_set() and result.status == "error"
        assert judge.requests == [] and result.details["usage"]["model_call_count"] == 1
        assert result.details["usage"]["input_tokens"] is None
        snapshot = result.model_dump_json()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert result.model_dump_json() == snapshot
