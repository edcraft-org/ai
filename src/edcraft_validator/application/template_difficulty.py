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
        "assessment_scope": "typical_instance_uniform_parameter_domain",
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
            status = "passed" if match == "matches" else "failed"
            if status == "failed":
                findings.append(
                    ToolFinding(
                        code="DIFFICULTY_MISMATCH",
                        message=(
                            "Typical instance estimated "
                            f"{judge.assessment.estimated_difficulty}; "
                            f"requested {candidate.difficulty}. "
                            + judge.assessment.reason
                        ),
                        field="difficulty",
                    )
                )
    return ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_TOOL,
        version="1.0.0",
        status=status,
        findings=findings,
        details=details,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
