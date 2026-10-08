"""Provider-neutral planning context and callable tool schemas."""

import copy
import json
from typing import Any

from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest


def generation_messages(request: StructuredGenerationRequest) -> list[dict[str, Any]]:
    """Offer tool purposes for selection; argument schemas arrive at call time."""
    messages = [message.copy() for message in request.messages]
    if not request.tool_catalogue:
        return messages
    catalogue = [
        {"name": tool["name"], "description": tool["description"]}
        for tool in request.tool_catalogue.definitions()
    ]
    context = {
        "role": "system",
        "content": (
            "Available validation checks follow as JSON. "
            "Select checks by their names and descriptions. "
            "Return the response matching the supplied schema now; tool calls occur in "
            "later turns. Planning arguments must be {}. At call time, use only "
            "the arguments in the supplied function schema; the application supplies "
            "the candidate and request-owned values.\n" + json.dumps(catalogue)
        ),
    }
    position = 1 if messages and messages[0]["role"] == "system" else 0
    messages.insert(position, context)
    return messages


def callable_tool(definition: dict[str, Any], bindings: dict[str, Any]) -> dict:
    """Hide application-owned arguments and definitions that only describe them."""
    schema = copy.deepcopy(definition["inputSchema"])
    for field in bindings:
        schema.get("properties", {}).pop(field, None)
    schema["required"] = [
        field for field in schema.get("required", []) if field not in bindings
    ]
    schema["additionalProperties"] = False
    definitions = schema.pop("$defs", {})
    needed = {}

    def retain_references(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name in definitions and name not in needed:
                    needed[name] = definitions[name]
                    retain_references(definitions[name])
            for child in value.values():
                retain_references(child)
        elif isinstance(value, list):
            for child in value:
                retain_references(child)

    retain_references(schema)
    if needed:
        schema["$defs"] = needed
    return {
        "type": "function",
        "function": {
            "name": definition["name"],
            "description": definition["description"],
            "parameters": schema,
        },
    }
