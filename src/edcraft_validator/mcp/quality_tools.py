"""Explicit quality assessment, outside the template validation catalogue."""

import os

from fastmcp import FastMCP

from edcraft_validator.application.code_quality import (
    CodeQualityReport,
    assess_code_question_quality,
)
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.quality import QualityRequest
from edcraft_validator.llm.embeddings import EmbeddingProviderFactory
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.tools.python_execution import PythonExecutionTool


def configured_quality_provider():
    return create_model_provider(
        TemplateProviderSelection(
            provider="soclaas", model=os.getenv("EDCRAFT_QUALITY_MODEL") or None
        )
    )


def register_quality_tools(
    server: FastMCP,
    *,
    provider_factory: JudgeProviderFactory,
    embedding_provider_factory: EmbeddingProviderFactory,
    execution_tool: PythonExecutionTool,
    execution_timeout_seconds: float,
    judge_timeout_seconds: float,
    embedding_timeout_seconds: float,
):
    @server.tool(
        name="assess_code_quality",
        version="1.0.0",
        tags={"quality:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        description=(
            "Explicit relevance and quality assessment of a complete concrete Python "
            "tracing MCQ against an author request. Separately reports bounded "
            "execution-backed canonical answer and distinct wrong option checks, "
            "explicit syntax/target/count requirements, embedding cosine similarity "
            "without a pass threshold, and advisory SocLaas rubric judgments of "
            "relevance, clarity, answerability and every option's plausibility. "
            "Assessed means measurements completed, never a correctness or overall "
            "quality pass. Technical failures and missing requirements remain failures "
            "regardless of similarity or judge ratings. Sends full question content "
            "to configured embedding and judge providers; may incur model cost."
        ),
    )
    async def assess_code_quality(
        question: CodeDifficultyQuestion, request: QualityRequest
    ) -> CodeQualityReport:
        return await assess_code_question_quality(
            question,
            request,
            provider_factory=provider_factory,
            embedding_provider_factory=embedding_provider_factory,
            execution_tool=execution_tool,
            execution_timeout_seconds=execution_timeout_seconds,
            judge_timeout_seconds=judge_timeout_seconds,
            embedding_timeout_seconds=embedding_timeout_seconds,
        )
