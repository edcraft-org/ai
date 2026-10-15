"""Assess the difficulty of a supplied MCQ, independently of correctness checks."""

import math
import time
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
from edcraft_validator.llm.judging import JudgeProviderFactory, JudgeRun, run_judge


class CodeDifficultyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["assess_code_difficulty"] = "assess_code_difficulty"
    version: Literal["1.0.0"] = "1.0.0"
    advisory: Literal[True] = True
    status: Literal["assessed", "error"] = "error"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question_sha256: str
    requested_difficulty: Difficulty | None
    rubric_version: str | None = None
    rubric_sha256: str | None = None
    assessment_conditions_version: str | None = None
    judge: JudgeRun[DifficultyAssessment] | None = None
    difficulty_match: DifficultyMatch | None = None
    error_code: str | None = None
    duration_ms: float = 0


async def assess_code_question_difficulty(
    question: CodeDifficultyQuestion,
    *,
    requested_difficulty: Difficulty | None = None,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float = 60,
) -> CodeDifficultyReport:
    if not math.isfinite(judge_timeout_seconds) or judge_timeout_seconds <= 0:
        raise ValueError("judge timeout must be finite and positive")
    # Validate the input contract and isolate caller state, without checking code
    # semantics, the answer, option correctness or execution eligibility.
    question = CodeDifficultyQuestion.model_validate_json(question.model_dump_json())
    started = time.perf_counter()
    report = CodeDifficultyReport(
        question_sha256=question.sha256,
        requested_difficulty=requested_difficulty,
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
        report.judge = await run_judge(
            request,
            provider_factory=provider_factory,
            timeout_seconds=judge_timeout_seconds,
        )
        judge = report.judge
        if judge.status == "completed":
            assessment = judge.assessment
            assert assessment is not None
            if {o.option_id for o in assessment.option_evidence} != {
                o.id for o in question.options
            }:
                judge.status = "error"
                judge.error_code = "JUDGE_OPTION_EVIDENCE_MISMATCH"
                judge.assessment = None
                if judge.model_calls:
                    judge.model_calls[-1].error = judge.error_code
                report.error_code = judge.error_code
            else:
                report.status = "assessed"
                if requested_difficulty is not None:
                    report.difficulty_match = compare_difficulty(
                        assessment.estimated_difficulty,
                        requested_difficulty,
                        assessment.confidence,
                        assessment.alternative_levels,
                    )
        else:
            report.error_code = judge.error_code
    report.duration_ms = (time.perf_counter() - started) * 1000
    return report
