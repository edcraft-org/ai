"""Discover domain-tagged tools from one MCP catalogue listing."""

import copy
from typing import Any, Protocol

from edcraft_validator.validation.check_contracts import CheckDefinition


class ToolCatalogueError(ValueError):
    """The MCP catalogue cannot supply tools for the selected domain."""


class ToolCatalogue(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...


def resolve_domain_tools(
    domain_name: str,
    catalogue: ToolCatalogue,
    *,
    capabilities: tuple[str, ...] | frozenset[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Return an ordered snapshot of tools offered to the selected domain.

    A tool is offered when it is tagged ``domain:<name>`` or when it is tagged
    ``capability:<name>`` for one of the domain's declared capabilities. Shared
    checks stay registered once while each domain selects them explicitly.
    """
    accepted = {f"domain:{domain_name}"}
    accepted.update(f"capability:{capability}" for capability in capabilities)
    listed = catalogue.list_tools()
    matched = [
        tool
        for tool in listed
        if accepted & set(tool.get("_meta", {}).get("fastmcp", {}).get("tags", []))
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


def check_definitions(definitions) -> dict[str, CheckDefinition]:
    """Decode MCP metadata once, before the application executes its frozen plan."""
    checks = {}
    for definition in definitions:
        if isinstance(definition, CheckDefinition):
            checks[definition.name] = definition
            continue
        metadata = definition.get("_meta", {}).get("fastmcp", {})
        name = definition["name"]
        checks[name] = CheckDefinition(
            name=name,
            input_schema=definition["inputSchema"],
            output_schema=definition.get("outputSchema"),
            version=metadata.get("version"),
            after_validation="stage:after-validation" in metadata.get("tags", []),
            advisory="policy:advisory" in metadata.get("tags", []),
        )
    return checks
