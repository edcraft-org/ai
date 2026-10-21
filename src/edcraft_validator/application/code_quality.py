"""Relevance checks with optional reuse of existing difficulty quality evidence."""

import asyncio
import json
import math
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from edcraft_validator.application.code_difficulty import CodeDifficultyReport
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion, Record
from edcraft_validator.domains.code.quality import (
    QualityRequest,
    rendered_question,
)
from edcraft_validator.llm.embeddings import (
    EmbeddingProviderFactory,
    SimilarityReport,
    measure_similarity,
)
from edcraft_validator.mcp.code_checks.code_features import extract_code_features
from edcraft_validator.tools.python_analysis import analyze_python_subset
from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)
from edcraft_validator.value_comparison import equivalent


class TechnicalCheck(Record):
    status: Literal["passed", "failed", "error"] = "error"
    canonical_answer: Any = None
    findings: list[str] = Field(default_factory=list)


class RequirementCheck(Record):
    status: Literal["satisfied", "missing", "unknown"]
    observed_features: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    limitation: str = (
        "Checks only requested syntax in reachable functions, target and option count. "
        "Syntax presence does not prove the requested concept affects the answer. "
        "Free-text requirement coverage is not verified."
    )


class ReusedDifficultyQuality(Record):
    status: Literal["reused", "not_supplied", "unavailable"] = "not_supplied"
    quality_concerns: list[str] | None = None
    # Retain the original rubric, settings, option evidence, usage and failures.
    # Usage belongs to that prior assessment, not this quality invocation.
    report: CodeDifficultyReport | None = None


def reuse_difficulty_quality(
    question: CodeDifficultyQuestion, report: CodeDifficultyReport | None
) -> ReusedDifficultyQuality:
    if report is None:
        return ReusedDifficultyQuality()
    report = CodeDifficultyReport.model_validate_json(
        report.model_dump_json(), strict=True
    )
    if report.question_sha256 != question.sha256:
        raise ValueError("difficulty report must match the exact supplied question")
    if (
        report.status != "assessed"
        or report.judge is None
        or report.judge.status != "completed"
        or report.judge.assessment is None
        or report.judge.assessment.estimated_difficulty is None
    ):
        return ReusedDifficultyQuality(status="unavailable", report=report)
    ids = [item.option_id for item in report.judge.assessment.option_evidence]
    if set(ids) != {item.id for item in question.options}:
        raise ValueError("difficulty evidence must cover the supplied options")
    return ReusedDifficultyQuality(
        status="reused",
        quality_concerns=list(report.judge.assessment.quality_concerns),
        report=report,
    )


class CodeQualityReport(Record):
    tool: Literal["assess_code_quality"] = "assess_code_quality"
    version: Literal["2.0.0"] = "2.0.0"
    advisory: Literal[True] = True
    status: Literal["assessed", "error"] = "error"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question_sha256: str
    request: QualityRequest
    technical: TechnicalCheck
    requirements: RequirementCheck
    similarity: SimilarityReport
    difficulty_quality: ReusedDifficultyQuality
    duration_ms: float = 0


def check_requirements(
    question: CodeDifficultyQuestion, request: QualityRequest
) -> RequirementCheck:
    try:
        observed = sorted(extract_code_features(question.code, question.entry_function))
    except (SyntaxError, ValueError, RecursionError):
        return RequirementCheck(status="unknown", findings=["FEATURES_UNAVAILABLE"])
    findings = [
        f"MISSING_FEATURE:{feature}"
        for feature in sorted(set(request.required_features) - set(observed))
    ]
    if request.answer_target and question.answer_target != request.answer_target:
        findings.append("ANSWER_TARGET_MISMATCH")
    if request.num_distractors and len(question.options) - 1 != request.num_distractors:
        findings.append("DISTRACTOR_COUNT_MISMATCH")
    return RequirementCheck(
        status="missing" if findings else "satisfied",
        observed_features=observed,
        findings=findings,
    )


def check_concrete_correctness(
    question: CodeDifficultyQuestion,
    execution_tool: PythonExecutionTool,
    timeout_seconds: float,
) -> TechnicalCheck:
    """Keep canonical answers and distinct wrong options mandatory and non-LLM."""
    if not analyze_python_subset(question.code, question.entry_function).is_valid:
        return TechnicalCheck(status="failed", findings=["UNSUPPORTED_CODE"])
    executions = execution_tool.execute_batch(
        question.code,
        question.entry_function,
        [question.inputs],
        timeout_seconds=timeout_seconds,
    )
    if len(executions) != 1:
        return TechnicalCheck(findings=["EXECUTOR_PROTOCOL_ERROR"])
    execution = executions[0]
    if not execution.ok:
        # Failed, unsupported or unavailable execution can never become a pass.
        return TechnicalCheck(findings=[execution.error_code or "EXECUTION_FAILED"])
    if question.answer_target == "return_value":
        answer = execution.answer
    elif (
        isinstance(execution.trace_summary, dict)
        and question.answer_target in execution.trace_summary
    ):
        answer = execution.trace_summary[question.answer_target]
    else:
        return TechnicalCheck(findings=["ANSWER_TARGET_UNAVAILABLE"])
    try:
        json.dumps(answer, allow_nan=False)
    except (TypeError, ValueError):
        return TechnicalCheck(findings=["INVALID_CANONICAL_ANSWER"])
    designated = next(
        o.value for o in question.options if o.id == question.correct_option
    )
    findings = []
    if not equivalent(designated, answer):
        findings.append("CANONICAL_ANSWER_MISMATCH")
    for index, option in enumerate(question.options):
        if option.id != question.correct_option and equivalent(option.value, answer):
            findings.append(f"DISTRACTOR_EQUALS_ANSWER:{option.id}")
        if any(equivalent(option.value, o.value) for o in question.options[:index]):
            findings.append(f"DUPLICATE_OPTION:{option.id}")
    return TechnicalCheck(
        status="failed" if findings else "passed",
        canonical_answer=answer,
        findings=findings,
    )


async def assess_code_question_quality(
    question: CodeDifficultyQuestion,
    request: QualityRequest,
    *,
    embedding_provider_factory: EmbeddingProviderFactory,
    difficulty_report: CodeDifficultyReport | None = None,
    execution_tool: PythonExecutionTool | None = None,
    embedding_timeout_seconds: float = 35,
    execution_timeout_seconds: float = 2,
) -> CodeQualityReport:
    for timeout in (
        embedding_timeout_seconds,
        execution_timeout_seconds,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("quality timeouts must be finite and positive")
    question = CodeDifficultyQuestion.model_validate_json(question.model_dump_json())
    request = QualityRequest.model_validate_json(request.model_dump_json())
    # Validate identity before execution or any paid request. Never reassess stale
    # or absent difficulty evidence and never infer an author-request match from it.
    difficulty_quality = reuse_difficulty_quality(question, difficulty_report)
    started = time.perf_counter()
    try:
        async with asyncio.timeout(execution_timeout_seconds + 2):
            technical = await asyncio.to_thread(
                check_concrete_correctness,
                question,
                execution_tool or LocalPythonTool(),
                execution_timeout_seconds,
            )
    except TimeoutError:
        technical = TechnicalCheck(findings=["EXECUTION_TIMEOUT"])
    except Exception:
        technical = TechnicalCheck(findings=["TECHNICAL_CHECK_ERROR"])
    requirements = check_requirements(question, request)
    similarity = await measure_similarity(
        json.dumps(request.model_dump(mode="json"), sort_keys=True, indent=2),
        rendered_question(question),
        provider_factory=embedding_provider_factory,
        timeout_seconds=embedding_timeout_seconds,
    )
    return CodeQualityReport(
        status="assessed" if similarity.status == "measured" else "error",
        question_sha256=question.sha256,
        request=request,
        technical=technical,
        requirements=requirements,
        similarity=similarity,
        difficulty_quality=difficulty_quality,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
