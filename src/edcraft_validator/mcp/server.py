"""FastMCP server exposing EdCraft's authoritative validation tools."""

from fastmcp import FastMCP

from edcraft_validator.mcp.code_tools import register_code_validation_tools
from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)


def create_validation_server(
    *,
    execution_tool: PythonExecutionTool | None = None,
    timeout_seconds: float = 2.0,
) -> FastMCP:
    """Build a validation server with injectable execution for tests/deployment."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    server = FastMCP(
        name="EdCraft Validation Tools",
        strict_input_validation=True,
        mask_error_details=True,
    )
    register_code_validation_tools(
        server,
        execution_tool=execution_tool or LocalPythonTool(),
        timeout_seconds=timeout_seconds,
    )
    return server


mcp = create_validation_server()
