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
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion, Record
from edcraft_validator.domains.code.question_checks import (
    RequirementCheck,
    TechnicalCheck,
)
from edcraft_validator.domains.code.relevance import (
    CodeQuestionRequest,
    relevance_input,
)
from edcraft_validator.llm.embeddings import EmbeddingProviderFactory
from edcraft_validator.relevance_contracts import RelevanceReport
from edcraft_validator.tools.python_execution import PythonExecutionTool


class CodeRelevanceReview(Record):
    """A caller-side collection, never an overall correctness or relevance pass."""

    version: Literal["4.0.0"] = "4.0.0"
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
    embedding_provider_factory: EmbeddingProviderFactory,
    execution_tool: PythonExecutionTool | None = None,
    embedding_timeout_seconds: float = 35,
    execution_timeout_seconds: float = 2,
) -> CodeRelevanceReview:
    for timeout in (embedding_timeout_seconds, execution_timeout_seconds):
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
        embedding_provider_factory=embedding_provider_factory,
        embedding_timeout_seconds=embedding_timeout_seconds,
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
