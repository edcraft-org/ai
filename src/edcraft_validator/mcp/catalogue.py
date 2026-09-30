"""Resolve domain tool allowlists against one MCP catalogue listing."""

import asyncio
import copy
from typing import Any, Protocol

from fastmcp import Client, FastMCP

from edcraft_validator.mcp.server import mcp


class ToolCatalogueError(ValueError):
    """The MCP catalogue cannot satisfy a domain's tool allowlist."""


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


def resolve_allowed_tools(
    allowed_names: tuple[str, ...], catalogue: ToolCatalogue
) -> tuple[dict[str, Any], ...]:
    """Return an ordered, independent snapshot of all allowed definitions."""
    if not allowed_names:
        raise ToolCatalogueError("domain has no allowed MCP tool names")
    if len(allowed_names) != len(set(allowed_names)):
        raise ToolCatalogueError("domain has duplicate allowed MCP tool names")

    listed = catalogue.list_tools()
    matches: dict[str, list[dict[str, Any]]] = {name: [] for name in allowed_names}
    for tool in listed:
        name = tool.get("name")
        if name in matches:
            matches[name].append(tool)

    missing = [name for name, definitions in matches.items() if not definitions]
    duplicate = [name for name, definitions in matches.items() if len(definitions) > 1]
    if missing or duplicate:
        issues = []
        if missing:
            issues.append("missing MCP tools: " + ", ".join(missing))
        if duplicate:
            issues.append("duplicate MCP tools: " + ", ".join(duplicate))
        raise ToolCatalogueError("; ".join(issues))

    resolved = tuple(copy.deepcopy(matches[name][0]) for name in allowed_names)
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
