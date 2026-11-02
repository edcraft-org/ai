"""Advisory template difficulty evidence, independent of technical correctness."""

import math
import time
from dataclasses import replace
from functools import cache

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.difficulty_matching import compare_difficulty
from edcraft_validator.domains.code.template_difficulty import (
    TEMPLATE_DIFFICULTY_TOOL,
    build_template_decision_request,
    build_template_difficulty_request,
    template_sha256,
)
from edcraft_validator.llm.forced_decision import run_decision
from edcraft_validator.llm.judge_configuration import configured_reasoning_effort
from edcraft_validator.llm.judging import (
    DEFAULT_JUDGE_TIMEOUT_SECONDS,
    JudgeProviderFactory,
    run_judge,
)
from edcraft_validator.llm.usage import summarize_usage
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding

HIGH_CONFIDENCE_THRESHOLD = 0.8
DECISION_CONFIDENCE_THRESHOLD = 0.7
DIFFICULTY_POLICY_VERSION = "decision-cascade-v1"


async def assess_template_difficulty(
    candidate: CodeTemplateCandidate,
    *,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
) -> ToolEvidence:
    if not math.isfinite(judge_timeout_seconds) or judge_timeout_seconds <= 0:
        raise ValueError("judge timeout must be finite and positive")
    started = time.perf_counter()
    candidate = CodeTemplateCandidate.model_validate(candidate.model_dump())
    details = {
        "advisory": True,
        "retryable": False,
        "assessment_scope": "typical_instance_uniform_eligible_combinations",
        "policy_version": DIFFICULTY_POLICY_VERSION,
        "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
        "confidence_calibrated": False,
        "decision_confidence_threshold": DECISION_CONFIDENCE_THRESHOLD,
        "template_sha256": template_sha256(candidate),
        "requested_difficulty": candidate.difficulty,
    }
    status = "error"
    findings = []
    try:
        rubric = load_code_difficulty_rubric()
        request = build_template_difficulty_request(candidate, rubric)
    except (OSError, ValueError):
        findings.append(
            ToolFinding(
                code="RUBRIC_UNAVAILABLE", message="Difficulty rubric unavailable"
            )
        )
    else:

        @cache
        def screen_provider():
            return provider_factory()

        screen = await run_decision(
            build_template_decision_request(candidate, rubric),
            labels=("easy", "medium", "hard"),
            provider_factory=screen_provider,
            timeout_seconds=min(35.0, judge_timeout_seconds),
        )
        accepted = (
            screen.status == "completed"
            and screen.assessment.confidence >= DECISION_CONFIDENCE_THRESHOLD
        )
        details["screen"] = screen.model_dump(mode="json")
        details["assessment_path"] = "decision" if accepted else "reasoning"
        if accepted:
            judge = screen
            estimate = screen.assessment.label
            confidence = screen.assessment.confidence
            reason = "Forced decision from first-token label probabilities."
            high_confidence = True
        else:
            # A timed-out classifier may still be running. Give the fallback its
            # own provider so late token usage cannot contaminate its report.
            # Structured-only injected providers are reused without a decision call.
            def reasoning_provider():
                provider = screen_provider()
                return (
                    provider_factory()
                    if callable(getattr(provider, "decide", None))
                    else provider
                )

            remaining = judge_timeout_seconds - (time.perf_counter() - started)
            try:
                effort = configured_reasoning_effort()
            except ValueError:
                effort = None
            if remaining <= 0 or effort is None:
                judge = screen.model_copy(
                    update={
                        "status": "error",
                        "assessment": None,
                        "error_code": "JUDGE_TIMEOUT"
                        if remaining <= 0
                        else "JUDGE_CONFIGURATION_ERROR",
                        "model_calls": [],
                        "usage": summarize_usage([]),
                    }
                )
            else:
                judge = await run_judge(
                    replace(request, reasoning_effort=effort),
                    provider_factory=reasoning_provider,
                    timeout_seconds=remaining,
                )
            estimate = (
                judge.assessment.estimated_difficulty if judge.assessment else None
            )
            confidence = judge.assessment.confidence if judge.assessment else None
            reason = judge.assessment.reason if judge.assessment else ""
            high_confidence = (
                confidence is not None and confidence >= HIGH_CONFIDENCE_THRESHOLD
            )
        calls = [*screen.model_calls, *(judge.model_calls if not accepted else [])]
        details.update(
            rubric_version=rubric.version,
            rubric_sha256=rubric.sha256,
            assessment_conditions_version=rubric.assessment_conditions_version,
            judge=judge.model_dump(mode="json"),
            usage=summarize_usage(calls).model_dump(mode="json"),
            model_calls=[call.model_dump(mode="json") for call in calls],
            estimated_difficulty=estimate,
            confidence=confidence,
            confidence_source="first_token_label_mass" if accepted else "self_reported",
        )
        if judge.status == "error":
            findings.append(
                ToolFinding(
                    code=judge.error_code or "JUDGE_FAILED",
                    message="Difficulty assessment failed; no check retry was made.",
                )
            )
        elif estimate is None:
            status = "failed"
            findings.append(
                ToolFinding(
                    code="DIFFICULTY_UNABLE_TO_ASSESS",
                    message=judge.assessment.unable_to_assess_reason,
                )
            )
        else:
            match = compare_difficulty(estimate, candidate.difficulty)
            details["difficulty_match"] = match
            details["decision"] = (
                "matches"
                if match == "matches"
                else "revise"
                if high_confidence
                else "advisory_mismatch"
            )
            status = "failed" if match != "matches" and high_confidence else "passed"
            if match != "matches":
                findings.append(
                    ToolFinding(
                        code="DIFFICULTY_MISMATCH"
                        if high_confidence
                        else "DIFFICULTY_MISMATCH_LOW_CONFIDENCE",
                        message=(
                            "Typical instance estimated "
                            f"{estimate}; "
                            f"requested {candidate.difficulty}. "
                            f"Confidence ({details['confidence_source']}) "
                            f"{confidence:.2f}. " + reason
                        ),
                        field="difficulty",
                    )
                )
    return ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_TOOL,
        version="1.2.0",
        status=status,
        findings=findings,
        details=details,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
