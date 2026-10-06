"""Discover domain-tagged tools from one MCP catalogue listing."""

import copy
from typing import Any, Protocol


class ToolCatalogueError(ValueError):
    """The MCP catalogue cannot supply tools for the selected domain."""


class ToolCatalogue(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...


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
