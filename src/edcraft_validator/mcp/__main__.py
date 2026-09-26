"""Run the EdCraft validation MCP server over stdio."""

from edcraft_validator.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
