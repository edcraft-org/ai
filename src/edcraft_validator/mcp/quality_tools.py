"""Explicit quality assessment, outside the template validation catalogue."""

import json
from typing import Annotated

from fastmcp import FastMCP
from pydantic import BeforeValidator

from edcraft_validator.application.code_difficulty import CodeDifficultyReport
from edcraft_validator.application.code_quality import (
    CodeQualityReport,
    assess_code_question_quality,
)
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.quality import QualityRequest
from edcraft_validator.llm.embeddings import EmbeddingProviderFactory
from edcraft_validator.tools.python_execution import PythonExecutionTool


def _report_from_wire(value):
    # MCP validates decoded Python values strictly, including datetimes. Parse
    # reports in strict JSON mode first so their ISO timestamp can round-trip.
    if isinstance(value, dict):
        return CodeDifficultyReport.model_validate_json(
            json.dumps(value, allow_nan=False), strict=True
        )
    return value


WireDifficultyReport = Annotated[
    CodeDifficultyReport, BeforeValidator(_report_from_wire)
]


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
        version="2.0.0",
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
            "without a pass threshold. Optionally reuses an existing concrete "
            "difficulty report's quality concerns and option evidence for the exact "
            "same question; never starts a difficulty or quality judge call. "
            "Absent evidence remains not_supplied, failed evidence unavailable. "
            "Assessed means measurements completed, never a correctness or overall "
            "quality pass. Technical failures and missing requirements remain failures "
            "regardless of similarity or reused opinions. Sends full learner-facing "
            "question content to the embedding provider; may incur model cost."
        ),
    )
    async def assess_code_quality(
        question: CodeDifficultyQuestion,
        request: QualityRequest,
        difficulty_report: WireDifficultyReport | None = None,
    ) -> CodeQualityReport:
        return await assess_code_question_quality(
            question,
            request,
            embedding_provider_factory=embedding_provider_factory,
            difficulty_report=difficulty_report,
            execution_tool=execution_tool,
            execution_timeout_seconds=execution_timeout_seconds,
            embedding_timeout_seconds=embedding_timeout_seconds,
        )
