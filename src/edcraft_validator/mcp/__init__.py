"""MCP adapters. Import server construction explicitly from mcp.server."""

from edcraft_validator.validation.check_contracts import (
    ToolEvidence,
    ToolFinding,
    ToolStatus,
)

__all__ = ["ToolEvidence", "ToolFinding", "ToolStatus", "create_validation_server"]


def create_validation_server(**dependencies):
    """Compatibility factory; importing contracts never constructs a server."""
    from edcraft_validator.mcp.server import create_validation_server as create_server

    return create_server(**dependencies)
