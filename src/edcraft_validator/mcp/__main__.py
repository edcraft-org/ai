"""Run the EdCraft validation MCP server over stdio."""

from edcraft_validator.mcp.server import create_validation_server

if __name__ == "__main__":
    create_validation_server().run()
