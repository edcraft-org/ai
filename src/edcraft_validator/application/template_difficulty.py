"""Template difficulty routing, policy and evidence as separate readable stages."""

import math
import time
from dataclasses import replace

from edcraft_validator.application.authoring_contracts import DifficultyOutcome
from edcraft_validator.domains.code.candidate_builder import template_sha256
from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.difficulty_matching import compare_difficulty
from edcraft_validator.domains.code.template_difficulty import (
    TEMPLATE_DIFFICULTY_TOOL,
    build_template_decision_request,
    build_template_difficulty_request,
)
from edcraft_validator.llm.forced_decision import (
    ClassDecision,
    JudgeProviderSession,
    run_decision,
)
from edcraft_validator.llm.judge_configuration import JudgeSettings
from edcraft_validator.llm.judging import (
    DEFAULT_JUDGE_TIMEOUT_SECONDS,
    JudgeProviderFactory,
    failed_judge,
    run_judge,
)
from edcraft_validator.llm.usage import summarize_usage
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding

HIGH_CONFIDENCE_THRESHOLD = 0.8
DECISION_CONFIDENCE_THRESHOLD = 0.7
DIFFICULTY_POLICY_VERSION = "decision-cascade-v1"


async def assess_template_difficulty(
    candidate: CodeTemplateCandidate,
    *,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
    settings: JudgeSettings | None = None,
) -> ToolEvidence:
    if not math.isfinite(judge_timeout_seconds) or judge_timeout_seconds <= 0:
        raise ValueError("judge timeout must be finite and positive")
    started = time.perf_counter()
    selected = settings if settings is not None else JudgeSettings()
    candidate = CodeTemplateCandidate.model_validate(candidate.model_dump())
    try:
        rubric = load_code_difficulty_rubric()
        decision_request = build_template_decision_request(candidate, rubric)
        reasoning_request = build_template_difficulty_request(candidate, rubric)
    except (OSError, ValueError):
        return ToolEvidence(
            tool=TEMPLATE_DIFFICULTY_TOOL,
            version="1.2.0",
            status="error",
            findings=[
                ToolFinding(
                    code="RUBRIC_UNAVAILABLE", message="Difficulty rubric unavailable"
                )
            ],
        )

    providers = JudgeProviderSession(provider_factory)
    screen = await run_decision(
        decision_request,
        labels=("easy", "medium", "hard"),
        provider_factory=providers.decision_provider,
        timeout_seconds=min(selected.decision_timeout_seconds, judge_timeout_seconds),
    )
    if _accept_decision(screen, selected):
        outcome = _policy_outcome(screen, candidate.difficulty, "decision", selected)
        return _build_evidence(
            candidate, rubric, selected, screen, None, outcome, started
        )

    remaining = judge_timeout_seconds - (time.perf_counter() - started)
    reasoning_request = replace(
        reasoning_request, reasoning_effort=selected.reasoning_effort
    )
    judge = (
        failed_judge(reasoning_request, "JUDGE_TIMEOUT", 0)
        if remaining <= 0
        else await run_judge(
            reasoning_request,
            provider_factory=providers.reasoning_provider,
            timeout_seconds=remaining,
        )
    )
    outcome = _policy_outcome(judge, candidate.difficulty, "reasoning", selected)
    return _build_evidence(candidate, rubric, selected, screen, judge, outcome, started)


def _accept_decision(screen, settings):
    return (
        screen.status == "completed"
        and screen.assessment.confidence >= settings.decision_threshold
    )


def _policy_outcome(judge, requested, path, settings):
    if judge.status == "error":
        return DifficultyOutcome(
            assessment_path=path,
            error_code=judge.error_code,
            reason="Difficulty assessment failed; no check retry was made.",
        )
    assessment = judge.assessment
    is_decision = isinstance(assessment, ClassDecision)
    estimate = assessment.label if is_decision else assessment.estimated_difficulty
    if estimate is None:
        return DifficultyOutcome(
            assessment_path=path,
            status="failed",
            error_code="DIFFICULTY_UNABLE_TO_ASSESS",
            reason=assessment.unable_to_assess_reason,
        )
    matches = compare_difficulty(estimate, requested) == "matches"
    decisive = is_decision or assessment.confidence >= settings.reasoning_threshold
    decision = "matches" if matches else "revise" if decisive else "advisory_mismatch"
    return DifficultyOutcome(
        assessment_path=path,
        estimated_difficulty=estimate,
        confidence=assessment.confidence,
        confidence_source="first_token_label_mass" if is_decision else "self_reported",
        decision=decision,
        status="failed" if decision == "revise" else "passed",
        reason="Forced decision from first-token label probabilities."
        if is_decision
        else assessment.reason,
    )


def _findings(outcome, requested):
    if outcome.error_code:
        return [ToolFinding(code=outcome.error_code, message=outcome.reason)]
    if outcome.decision == "matches":
        return []
    return [
        ToolFinding(
            code="DIFFICULTY_MISMATCH"
            if outcome.decision == "revise"
            else "DIFFICULTY_MISMATCH_LOW_CONFIDENCE",
            message=(
                f"Typical instance estimated {outcome.estimated_difficulty}; "
                f"requested {requested}. Confidence ({outcome.confidence_source}) "
                f"{outcome.confidence:.2f}. {outcome.reason}"
            ),
            field="difficulty",
        )
    ]


def _build_evidence(candidate, rubric, settings, screen, reasoning, outcome, started):
    judge = screen if reasoning is None else reasoning
    calls = [*screen.model_calls, *(reasoning.model_calls if reasoning else [])]
    details = {
        "advisory": True,
        "retryable": False,
        "assessment_scope": "typical_instance_uniform_eligible_combinations",
        "policy_version": DIFFICULTY_POLICY_VERSION,
        "high_confidence_threshold": settings.reasoning_threshold,
        "decision_confidence_threshold": settings.decision_threshold,
        "confidence_calibrated": False,
        "template_sha256": template_sha256(candidate),
        "requested_difficulty": candidate.difficulty,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "assessment_conditions_version": rubric.assessment_conditions_version,
        "screen": screen.model_dump(mode="json"),
        "judge": judge.model_dump(mode="json"),
        "difficulty_outcome": outcome.model_dump(mode="json"),
        "usage": summarize_usage(calls).model_dump(mode="json"),
        "model_calls": [call.model_dump(mode="json") for call in calls],
        # Retain the existing flat fields while clients migrate to the typed outcome.
        **outcome.model_dump(
            mode="json",
            include={
                "assessment_path",
                "estimated_difficulty",
                "confidence",
                "confidence_source",
                "decision",
            },
        ),
    }
    if outcome.estimated_difficulty is not None:
        details["difficulty_match"] = compare_difficulty(
            outcome.estimated_difficulty, candidate.difficulty
        )
    return ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_TOOL,
        version="1.2.0",
        status=outcome.status,
        findings=_findings(outcome, candidate.difficulty),
        details=details,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
