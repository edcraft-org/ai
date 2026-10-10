"""Discover tools by domain tags and retain one catalogue per authoring job."""

import copy
from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel

from edcraft_validator.application.authoring_contracts import AuthoringFailure
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.llm.llm_contracts import ToolCatalogueSnapshot
from edcraft_validator.mcp.catalogue import (
    resolve_domain_tools,
)
from edcraft_validator.mcp.client import FastMcpToolClient


class RecordingCatalogue:
    def __init__(self, tools):
        self.tools = tools
        self.calls = 0

    def list_tools(self):
        self.calls += 1
        return self.tools


class EmptyRequest(BaseModel):
    pass


def definition(name, domains=("code",)):
    return {
        "name": name,
        "description": f"Check {name}",
        "inputSchema": {"type": "object", "properties": {"candidate": {}}},
        "outputSchema": {"type": "object", "properties": {"status": {}}},
        "_meta": {
            "fastmcp": {
                "version": "1.0",
                "tags": [f"domain:{domain}" for domain in domains],
            }
        },
    }


def test_code_domain_resolves_real_tagged_mcp_definitions():
    with FastMcpToolClient() as client:
        tools = resolve_domain_tools("code", client)

    assert [tool["name"] for tool in tools] == [
        "code_require_features",
        "code_validate_answers_and_distractors",
        "code_verify_template_structure",
    ]
    assert all(tool["description"] for tool in tools)
    assert all("candidate" in tool["inputSchema"]["properties"] for tool in tools)
    assert all("status" in tool["outputSchema"]["properties"] for tool in tools)
    assert all(tool["_meta"]["fastmcp"]["version"] for tool in tools)


def test_domain_tags_filter_tools_and_allow_shared_tools():
    catalogue = RecordingCatalogue(
        [
            definition("math_only", ("math",)),
            definition("shared", ("code", "math")),
            definition("untagged", ()),
            definition("code_only"),
        ]
    )
    assert [tool["name"] for tool in resolve_domain_tools("code", catalogue)] == [
        "code_only",
        "shared",
    ]
    assert [tool["name"] for tool in resolve_domain_tools("math", catalogue)] == [
        "math_only",
        "shared",
    ]


def test_new_tagged_tool_is_discovered_without_a_domain_tool_list():
    catalogue = RecordingCatalogue([definition("original")])
    assert [tool["name"] for tool in resolve_domain_tools("code", catalogue)] == [
        "original"
    ]
    catalogue.tools.append(definition("new_check"))
    assert [tool["name"] for tool in resolve_domain_tools("code", catalogue)] == [
        "new_check",
        "original",
    ]


@pytest.mark.parametrize(
    ("listed", "message"),
    [
        ([], "no MCP tools tagged for domain: code"),
        ([definition("math_only", ("math",))], "no MCP tools tagged for domain: code"),
        ([definition("untagged", ())], "no MCP tools tagged for domain: code"),
        ([definition("check"), definition("check")], "duplicate MCP tools: check"),
    ],
)
def test_bad_catalogue_stops_before_generation(listed, message):
    catalogue = RecordingCatalogue(listed)

    class Domain:
        name = "code"

        def generation_request(self, request):
            pytest.fail("invalid catalogues must stop before prompt construction")

    class Provider:
        provider = "scripted"
        model = "scripted"

        def generate(self, request):
            pytest.fail("invalid catalogues must stop before model generation")

    with pytest.raises(AuthoringFailure, match=message) as failure:
        TemplateApplication(tool_catalogue=catalogue).create_validated_template(
            EmptyRequest(), domain=Domain(), provider=Provider()
        )
    assert catalogue.calls == 1
    assert failure.value.result.failure.stage == "configuration"
    assert failure.value.result.failure.code == "MCP_CATALOGUE_ERROR"
    assert failure.value.result.usage.model_call_count == 0


def test_resolution_reads_once_and_copies_full_definitions():
    original = definition("check")
    catalogue = RecordingCatalogue([original])
    resolved = resolve_domain_tools("code", catalogue)
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
