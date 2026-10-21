"""Explicit quality assessment, outside the template validation catalogue."""

from fastmcp import FastMCP

from edcraft_validator.application.code_quality import (
    CodeQualityReport,
    assess_code_question_quality,
)
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.quality import QualityRequest
from edcraft_validator.llm.embeddings import EmbeddingProviderFactory
from edcraft_validator.tools.python_execution import PythonExecutionTool


def register_quality_tools(
    server: FastMCP,
    *,
    embedding_provider_factory: EmbeddingProviderFactory,
    execution_tool: PythonExecutionTool,
    execution_timeout_seconds: float,
    embedding_timeout_seconds: float,
):
    @server.tool(
        name="assess_code_quality",
        version="3.0.0",
        tags={"quality:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        description=(
            "Independent relevance assessment of a complete concrete Python "
            "tracing MCQ against an author request. Separately reports bounded "
            "execution-backed canonical answer and distinct wrong option checks, "
            "explicit syntax/target/count requirements, embedding cosine similarity "
            "without a pass threshold. Accepts only the question and author request; "
            "never consumes another check's report or starts a generative judge call. "
            "Difficulty judgments and their quality concerns remain separate. "
            "Assessed means measurements completed, never a correctness or overall "
            "quality pass. Technical failures and missing requirements remain failures "
            "regardless of similarity. Sends full learner-facing "
            "question content to the embedding provider; may incur model cost."
        ),
    )
    async def assess_code_quality(
        question: CodeDifficultyQuestion,
        request: QualityRequest,
    ) -> CodeQualityReport:
        return await assess_code_question_quality(
            question,
            request,
            embedding_provider_factory=embedding_provider_factory,
            execution_tool=execution_tool,
            execution_timeout_seconds=execution_timeout_seconds,
            embedding_timeout_seconds=embedding_timeout_seconds,
        )
