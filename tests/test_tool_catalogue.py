"""The application resolves one authoritative tool catalogue per authoring job."""

import copy
from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.llm.llm_contracts import ToolCatalogueSnapshot
from edcraft_validator.mcp.catalogue import (
    FastMcpToolCatalogue,
    ToolCatalogueError,
    resolve_allowed_tools,
)


class RecordingCatalogue:
    def __init__(self, tools):
        self.tools = tools
        self.calls = 0

    def list_tools(self):
        self.calls += 1
        return self.tools


class EmptyRequest(BaseModel):
    pass


def definition(name):
    return {
        "name": name,
        "description": f"Check {name}",
        "inputSchema": {"type": "object", "properties": {"candidate": {}}},
        "outputSchema": {"type": "object", "properties": {"status": {}}},
        "_meta": {"fastmcp": {"version": "1.0"}},
    }


def test_code_domain_resolves_real_mcp_definitions():
    domain = CodeDomain()
    tools = resolve_allowed_tools(domain.allowed_tool_names, FastMcpToolCatalogue())

    assert [tool["name"] for tool in tools] == list(domain.allowed_tool_names)
    assert all(tool["description"] for tool in tools)
    assert all("candidate" in tool["inputSchema"]["properties"] for tool in tools)
    assert all("status" in tool["outputSchema"]["properties"] for tool in tools)
    assert all(tool["_meta"]["fastmcp"]["version"] for tool in tools)


@pytest.mark.parametrize(
    ("allowed", "listed", "message", "calls"),
    [
        (("missing",), [], "missing MCP tools: missing", 1),
        (
            ("check",),
            [definition("check"), definition("check")],
            "duplicate MCP tools: check",
            1,
        ),
        (
            ("check", "check"),
            [definition("check")],
            "duplicate allowed MCP tool names",
            0,
        ),
        ((), [], "no allowed MCP tool names", 0),
    ],
)
def test_bad_allowlist_stops_before_generation(allowed, listed, message, calls):
    catalogue = RecordingCatalogue(listed)

    class Domain:
        allowed_tool_names = allowed

        def generation_request(self, request):
            pytest.fail("invalid catalogues must stop before prompt construction")

    class Provider:
        def generate(self, request):
            pytest.fail("invalid catalogues must stop before model generation")

    with pytest.raises(ToolCatalogueError, match=message):
        TemplateApplication(tool_catalogue=catalogue).create_validated_template(
            EmptyRequest(), domain=Domain(), provider=Provider()
        )
    assert catalogue.calls == calls


def test_resolution_reads_once_and_copies_full_definitions():
    original = definition("check")
    catalogue = RecordingCatalogue([original])
    resolved = resolve_allowed_tools(("check",), catalogue)
    expected = copy.deepcopy(original)
    original["description"] = "changed after resolution"
    original["inputSchema"]["properties"].clear()

    assert catalogue.calls == 1
    assert resolved == (expected,)


def test_snapshot_cannot_be_changed_through_its_fields_or_returned_definitions():
    source = definition("check")
    snapshot = ToolCatalogueSnapshot.from_definitions((source,))
    source["description"] = "changed after snapshot"
    copy_of_definitions = snapshot.definitions()
    copy_of_definitions[0]["inputSchema"]["properties"].clear()

    with pytest.raises(FrozenInstanceError):
        snapshot.names = ("other",)
    assert snapshot.names == ("check",)
    assert snapshot.definitions()[0]["description"] == "Check check"
    assert "candidate" in snapshot.definitions()[0]["inputSchema"]["properties"]
