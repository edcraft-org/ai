"""Assess the difficulty of a supplied MCQ, independently of correctness checks."""

import json
import math
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.domains.code.code_types import Difficulty
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    DifficultyAssessment,
    build_difficulty_request,
    load_code_difficulty_rubric,
)
from edcraft_validator.domains.code.difficulty_matching import (
    DifficultyMatch,
    compare_difficulty,
)
from edcraft_validator.llm.judging import (
    JudgeProviderFactory,
    JudgeRun,
    JudgeValidationFinding,
    run_judge,
)
from edcraft_validator.llm.usage import ModelUsageSummary, summarize_usage

MAX_DIFFICULTY_CORRECTIONS = 3


class CodeDifficultyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["assess_code_difficulty"] = "assess_code_difficulty"
    version: Literal["2.0.0"] = "2.0.0"
    advisory: Literal[True] = True
    status: Literal["assessed", "unable_to_assess", "error"] = "error"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question_sha256: str
    requested_difficulty: Difficulty | None
    rubric_version: str | None = None
    rubric_sha256: str | None = None
    assessment_conditions_version: str | None = None
    judge: JudgeRun[DifficultyAssessment] | None = None
    judge_attempts: list[JudgeRun[DifficultyAssessment]] = Field(default_factory=list)
    max_correction_attempts: int = MAX_DIFFICULTY_CORRECTIONS
    usage: ModelUsageSummary = Field(default_factory=ModelUsageSummary)
    difficulty_match: DifficultyMatch | None = None
    error_code: str | None = None
    duration_ms: float = 0


async def assess_code_question_difficulty(
    question: CodeDifficultyQuestion,
    *,
    requested_difficulty: Difficulty | None = None,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float = 60,
    max_correction_attempts: int = MAX_DIFFICULTY_CORRECTIONS,
) -> CodeDifficultyReport:
    if not math.isfinite(judge_timeout_seconds) or judge_timeout_seconds <= 0:
        raise ValueError("judge timeout must be finite and positive")
    if (
        type(max_correction_attempts) is not int
        or not 0 <= max_correction_attempts <= 3
    ):
        raise ValueError("max_correction_attempts must be an integer from 0 to 3")
    # Validate the input contract and isolate caller state, without checking code
    # semantics, the answer, option correctness or execution eligibility.
    question = CodeDifficultyQuestion.model_validate_json(question.model_dump_json())
    started = time.perf_counter()
    report = CodeDifficultyReport(
        question_sha256=question.sha256,
        requested_difficulty=requested_difficulty,
        max_correction_attempts=max_correction_attempts,
    )
    try:
        rubric = load_code_difficulty_rubric()
        request = build_difficulty_request(question, rubric)
    except (OSError, ValueError):
        report.error_code = "RUBRIC_UNAVAILABLE"
    else:
        report.rubric_version = rubric.version
        report.rubric_sha256 = rubric.sha256
        report.assessment_conditions_version = rubric.assessment_conditions_version
        for _ in range(max_correction_attempts + 1):
            judge = await run_judge(
                request,
                provider_factory=provider_factory,
                timeout_seconds=judge_timeout_seconds,
            )
            if judge.status == "completed":
                assessment = judge.assessment
                assert assessment is not None
                if {o.option_id for o in assessment.option_evidence} != {
                    o.id for o in question.options
                }:
                    judge.status = "error"
                    judge.error_code = "JUDGE_OPTION_EVIDENCE_MISMATCH"
                    judge.validation_errors.append(
                        JudgeValidationFinding(
                            location=["option_evidence"],
                            code="option_ids_mismatch",
                            message="Explain each supplied option exactly once: "
                            + ", ".join(o.id for o in question.options),
                        )
                    )
                    judge.assessment = None
                    if judge.model_calls:
                        judge.model_calls[-1].error = judge.error_code
            report.judge = judge
            report.judge_attempts.append(judge)
            if judge.status == "completed":
                assessment = judge.assessment
                if assessment.estimated_difficulty is None:
                    report.status = "unable_to_assess"
                else:
                    report.status = "assessed"
                    if requested_difficulty is not None:
                        report.difficulty_match = compare_difficulty(
                            assessment.estimated_difficulty,
                            requested_difficulty,
                        )
                report.error_code = None
                break
            report.error_code = judge.error_code
            if judge.error_code in {
                "JUDGE_CONFIGURATION_ERROR",
                "JUDGE_INTERNAL_ERROR",
            }:
                break
            request = difficulty_repair_request(request, judge)
    report.usage = summarize_usage(
        [call for attempt in report.judge_attempts for call in attempt.model_calls]
    )
    report.duration_ms = (time.perf_counter() - started) * 1000
    return report


def difficulty_repair_request(request, failed_judge):
    """Only output diagnostics; no requested level or human reference is available."""
    feedback = {
        "assessment_error": failed_judge.error_code,
        "validation_findings": [f.model_dump() for f in failed_judge.validation_errors],
        "instruction": (
            "Return a complete assessment of the unchanged original question. "
            "Correct the reported output issues. Do not change the question. "
            "A transport failure provides no evidence about its difficulty."
        ),
    }
    return replace(
        request,
        messages=[*request.messages, {"role": "user", "content": json.dumps(feedback)}],
    )
