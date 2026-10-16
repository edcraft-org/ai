"""Advisory template difficulty evidence, independent of technical correctness."""

import time

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.difficulty_matching import compare_difficulty
from edcraft_validator.domains.code.template_difficulty import (
    TEMPLATE_DIFFICULTY_TOOL,
    build_template_difficulty_request,
    template_sha256,
)
from edcraft_validator.llm.judging import JudgeProviderFactory, run_judge
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding

HIGH_CONFIDENCE_THRESHOLD = 0.8
DIFFICULTY_POLICY_VERSION = "confidence-gated-v1"


async def assess_template_difficulty(
    candidate: CodeTemplateCandidate,
    *,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float = 60,
) -> ToolEvidence:
    started = time.perf_counter()
    candidate = CodeTemplateCandidate.model_validate_json(candidate.model_dump_json())
    details = {
        "advisory": True,
        "retryable": False,
        "assessment_scope": "typical_instance_uniform_eligible_combinations",
        "policy_version": DIFFICULTY_POLICY_VERSION,
        "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
        "confidence_calibrated": False,
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
        judge = await run_judge(
            request,
            provider_factory=provider_factory,
            timeout_seconds=judge_timeout_seconds,
        )
        details.update(
            rubric_version=rubric.version,
            rubric_sha256=rubric.sha256,
            assessment_conditions_version=rubric.assessment_conditions_version,
            judge=judge.model_dump(mode="json"),
            usage=judge.usage.model_dump(mode="json"),
        )
        if judge.status == "error":
            findings.append(
                ToolFinding(
                    code=judge.error_code or "JUDGE_FAILED",
                    message="Difficulty assessment failed; no check retry was made.",
                )
            )
        elif judge.assessment.estimated_difficulty is None:
            status = "failed"
            findings.append(
                ToolFinding(
                    code="DIFFICULTY_UNABLE_TO_ASSESS",
                    message=judge.assessment.unable_to_assess_reason,
                )
            )
        else:
            match = compare_difficulty(
                judge.assessment.estimated_difficulty, candidate.difficulty
            )
            details["difficulty_match"] = match
            high_confidence = judge.assessment.confidence >= HIGH_CONFIDENCE_THRESHOLD
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
                            f"{judge.assessment.estimated_difficulty}; "
                            f"requested {candidate.difficulty}. "
                            "Self-reported confidence "
                            f"{judge.assessment.confidence:.2f}. "
                            + judge.assessment.reason
                        ),
                        field="difficulty",
                    )
                )
    return ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_TOOL,
        version="1.1.0",
        status=status,
        findings=findings,
        details=details,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
