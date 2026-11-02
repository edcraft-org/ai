"""Default dependency construction for CLI and worker entry points."""


def create_tool_client():
    from edcraft_validator.mcp.client import FastMcpToolClient
    from edcraft_validator.mcp.server import create_validation_server

    return FastMcpToolClient(create_validation_server())
