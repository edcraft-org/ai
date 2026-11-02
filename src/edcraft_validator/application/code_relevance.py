"""Collect independent Python checks and shared relevance evidence for review."""

import math
import time
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from edcraft_validator.application.code_checks import (
    check_code_question_correctness,
    check_code_question_requirements,
)
from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.domains.code.candidate_builder import template_sha256
from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion, Record
from edcraft_validator.domains.code.question_checks import (
    RequirementCheck,
    TechnicalCheck,
)
from edcraft_validator.domains.code.relevance import (
    TEMPLATE_RELEVANCE_TOOL,
    CodeQuestionRequest,
    relevance_input,
    template_relevance_input,
)
from edcraft_validator.llm.decision import DecisionProviderFactory
from edcraft_validator.relevance_contracts import RelevanceReport
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding


class CodeRelevanceReview(Record):
    """A caller-side collection, never an overall correctness or relevance pass."""

    version: Literal["5.0.0"] = "5.0.0"
    advisory: Literal[True] = True
    status: Literal["assessed", "error"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question_sha256: str
    request: CodeQuestionRequest
    technical: TechnicalCheck
    requirements: RequirementCheck
    relevance: RelevanceReport
    duration_ms: float = Field(ge=0)


async def review_code_question_relevance(
    question: CodeDifficultyQuestion,
    request: CodeQuestionRequest,
    *,
    decision_provider_factory: DecisionProviderFactory,
    execution_tool: PythonExecutionTool | None = None,
    relevance_timeout_seconds: float = 35,
    execution_timeout_seconds: float = 2,
) -> CodeRelevanceReview:
    for timeout in (relevance_timeout_seconds, execution_timeout_seconds):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("review timeouts must be finite and positive")
    # Snapshot caller-owned lists and options for the asynchronous review.
    question = question.model_copy(deep=True)
    request = request.model_copy(deep=True)
    representation = relevance_input(question, request)
    started = time.perf_counter()
    technical = await check_code_question_correctness(
        question,
        execution_tool=execution_tool,
        execution_timeout_seconds=execution_timeout_seconds,
    )
    requirements = check_code_question_requirements(question, request)
    relevance = await assess_relevance(
        representation,
        decision_provider_factory=decision_provider_factory,
        relevance_timeout_seconds=relevance_timeout_seconds,
    )
    return CodeRelevanceReview(
        status=relevance.status,
        question_sha256=question.sha256,
        request=request,
        technical=technical,
        requirements=requirements,
        relevance=relevance,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


async def assess_code_template_relevance(
    candidate: CodeTemplateCandidate,
    author_request: str,
    *,
    decision_provider_factory: DecisionProviderFactory,
    relevance_timeout_seconds: float = 35,
) -> ToolEvidence:
    """Map the independent relevance decision into the authoring check contract."""
    candidate = CodeTemplateCandidate.model_validate(candidate.model_dump())
    report = await assess_relevance(
        template_relevance_input(candidate, author_request),
        decision_provider_factory=decision_provider_factory,
        relevance_timeout_seconds=relevance_timeout_seconds,
    )
    status = "passed"
    findings = []
    if report.status == "error":
        status = "error"
        findings = [
            ToolFinding(
                code=report.decision.error_code or "RELEVANCE_FAILED",
                message="Relevance assessment failed; no check retry was made.",
            )
        ]
    elif not report.decision.relevant:
        status = "failed"
        findings = [
            ToolFinding(
                code="RELEVANCE_MISMATCH",
                message=(
                    "The template may not assess the original author request; "
                    "this is advisory evidence for educator review, not a "
                    "technical failure or a revision request."
                ),
            )
        ]
    unavailable = report.status != "assessed"
    return ToolEvidence(
        tool=TEMPLATE_RELEVANCE_TOOL,
        version="1.0.0",
        status=status,
        findings=findings,
        details={
            "advisory": True,
            "retryable": False,
            "template_sha256": template_sha256(candidate),
            "score": report.decision.score,
            "threshold": report.decision.threshold,
            "relevant": report.decision.relevant,
            "provider": report.decision.provider,
            "model": report.decision.model,
            "usage": report.decision.usage.model_dump(mode="json"),
            "relevance": report.model_dump(mode="json"),
            "relevance_outcome": {
                "status": "unavailable" if unavailable else "assessed",
                "unavailable": unavailable,
                "score": report.decision.score,
                "threshold": report.decision.threshold,
                "relevant": report.decision.relevant,
                "reason": (
                    "Relevance assessment unavailable; no check retry was made."
                    if unavailable
                    else "Advisory relevance assessment completed."
                ),
                "error_code": report.decision.error_code,
            },
        },
        duration_ms=report.duration_ms,
    )
