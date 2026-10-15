"""FastMCP server exposing technical checks and separate advisory assessments."""

import math

from fastmcp import FastMCP

from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.mcp.code_tools import register_code_validation_tools
from edcraft_validator.mcp.difficulty_tools import (
    configured_difficulty_provider,
    register_difficulty_tools,
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
    difficulty_max_correction_attempts: int = 3,
) -> FastMCP:
    """Build the centralized server with injectable code-domain dependencies."""
    for timeout in (code_execution_timeout_seconds, difficulty_judge_timeout_seconds):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("tool timeouts must be finite and positive")
    if (
        type(difficulty_max_correction_attempts) is not int
        or not 0 <= difficulty_max_correction_attempts <= 3
    ):
        raise ValueError("difficulty_max_correction_attempts must be from 0 to 3")
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
        max_correction_attempts=difficulty_max_correction_attempts,
    )
    return server


mcp = create_validation_server()
