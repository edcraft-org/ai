"""Discover domain-tagged tools from one MCP catalogue listing."""

import asyncio
import copy
from typing import Any, Protocol

from fastmcp import Client, FastMCP

from edcraft_validator.mcp.server import mcp


class ToolCatalogueError(ValueError):
    """The MCP catalogue cannot supply tools for the selected domain."""


class ToolCatalogue(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...


class FastMcpToolCatalogue:
    """Use MCP tools/list without exposing the server's internal registry."""

    def __init__(self, server: FastMCP | None = None) -> None:
        self.server = server if server is not None else mcp

    def list_tools(self) -> list[dict[str, Any]]:
        async def fetch() -> list[dict[str, Any]]:
            async with Client(self.server) as client:
                tools = await client.list_tools(cache_mode="refresh")
            return [
                tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                for tool in tools
            ]

        try:
            return asyncio.run(fetch())
        except Exception as exc:
            raise ToolCatalogueError(f"Could not list MCP tools: {exc}") from exc


def resolve_domain_tools(
    domain_name: str, catalogue: ToolCatalogue
) -> tuple[dict[str, Any], ...]:
    """Return an ordered snapshot of tools tagged for the selected domain."""
    tag = f"domain:{domain_name}"
    listed = catalogue.list_tools()
    matched = [
        tool
        for tool in listed
        if tag in tool.get("_meta", {}).get("fastmcp", {}).get("tags", [])
    ]
    if not matched:
        raise ToolCatalogueError(f"no MCP tools tagged for domain: {domain_name}")
    names = [tool["name"] for tool in matched]
    duplicate = sorted({name for name in names if names.count(name) > 1})
    if duplicate:
        raise ToolCatalogueError("duplicate MCP tools: " + ", ".join(duplicate))
    resolved = tuple(
        copy.deepcopy(tool) for tool in sorted(matched, key=lambda t: t["name"])
    )
    for tool in resolved:
        if not tool.get("description") or not isinstance(tool.get("inputSchema"), dict):
            raise ToolCatalogueError(
                f"MCP tool {tool['name']!r} lacks a description or input schema"
            )
        if "outputSchema" in tool and not isinstance(tool["outputSchema"], dict):
            raise ToolCatalogueError(
                f"MCP tool {tool['name']!r} has an invalid output schema"
            )
    return resolved
