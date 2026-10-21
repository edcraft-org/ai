"""FastMCP server exposing technical checks and separate advisory assessments."""

import math

from fastmcp import FastMCP

from edcraft_validator.llm.embeddings import (
    EmbeddingProviderFactory,
    OpenAIEmbeddingProvider,
)
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.mcp.code_tools import register_code_validation_tools
from edcraft_validator.mcp.difficulty_tools import (
    configured_difficulty_provider,
    register_difficulty_tools,
)
from edcraft_validator.mcp.quality_tools import (
    configured_quality_provider,
    register_quality_tools,
)
from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)


def create_validation_server(
    *,
    code_execution_tool: PythonExecutionTool | None = None,
    code_execution_timeout_seconds: float = 2.0,
    difficulty_provider_factory: JudgeProviderFactory | None = None,
    difficulty_judge_timeout_seconds: float = 60.0,
    quality_provider_factory: JudgeProviderFactory | None = None,
    embedding_provider_factory: EmbeddingProviderFactory | None = None,
    quality_judge_timeout_seconds: float = 60.0,
    embedding_timeout_seconds: float = 35.0,
) -> FastMCP:
    """Build the centralized server with injectable code-domain dependencies."""
    for timeout in (
        code_execution_timeout_seconds,
        difficulty_judge_timeout_seconds,
        quality_judge_timeout_seconds,
        embedding_timeout_seconds,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("tool timeouts must be finite and positive")
    server = FastMCP(
        name="EdCraft Validation Tools",
        strict_input_validation=True,
        mask_error_details=True,
    )
    execution_tool = code_execution_tool or LocalPythonTool()
    register_code_validation_tools(
        server,
        execution_tool=execution_tool,
        timeout_seconds=code_execution_timeout_seconds,
    )
    register_difficulty_tools(
        server,
        provider_factory=difficulty_provider_factory or configured_difficulty_provider,
        judge_timeout_seconds=difficulty_judge_timeout_seconds,
    )
    register_quality_tools(
        server,
        provider_factory=quality_provider_factory or configured_quality_provider,
        embedding_provider_factory=embedding_provider_factory
        or OpenAIEmbeddingProvider,
        execution_tool=execution_tool,
        execution_timeout_seconds=code_execution_timeout_seconds,
        judge_timeout_seconds=quality_judge_timeout_seconds,
        embedding_timeout_seconds=embedding_timeout_seconds,
    )
    return server


mcp = create_validation_server()
