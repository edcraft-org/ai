"""One synchronous job-scoped connection to the asynchronous MCP server."""

import asyncio
from typing import Any

from fastmcp import Client

from edcraft_validator.mcp.catalogue import ToolCatalogueError
from edcraft_validator.mcp.server import mcp


class FastMcpToolClient:
    def __init__(self, server=None, *, timeout_seconds: float = 135):
        self.server = server if server is not None else mcp
        self.timeout_seconds = timeout_seconds

    def __enter__(self):
        self.runner = asyncio.Runner()
        self.client = Client(self.server, timeout=self.timeout_seconds)
        try:
            self.runner.run(self.client.__aenter__())
        except Exception:
            self.runner.close()
            raise
        return self

    def __exit__(self, *args):
        try:
            self.runner.run(self.client.__aexit__(*args))
        finally:
            self.runner.close()

    def list_tools(self) -> list[dict[str, Any]]:
        try:
            return [
                tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                for tool in self.runner.run(
                    self.client.list_tools(cache_mode="refresh")
                )
            ]
        except Exception as exc:
            raise ToolCatalogueError("Could not list MCP tools") from exc

    def call_tool(self, name, arguments, *, version=None) -> dict[str, Any]:
        result = self.runner.run(
            self.client.call_tool(
                name,
                arguments,
                version=version,
                timeout=self.timeout_seconds,
            )
        )
        if not isinstance(result.structured_content, dict):
            raise ValueError("MCP returned no structured evidence")
        return result.structured_content
