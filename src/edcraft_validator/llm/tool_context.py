"""Provider-neutral model context for the frozen MCP tool catalogue."""

from typing import Any

from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest


def generation_messages(request: StructuredGenerationRequest) -> list[dict[str, Any]]:
    """Supply complete MCP definitions without executing tools in this phase."""
    messages = [message.copy() for message in request.messages]
    if not request.tool_catalogue:
        return messages
    catalogue = request.tool_catalogue.definitions_json
    context = {
        "role": "system",
        "content": (
            "Available MCP validation tools for this generation job follow as JSON. "
            "Their names, descriptions, input schemas, output schemas, annotations, "
            "and metadata are authoritative. Recommend checks only from these tools. "
            "Return the response matching the supplied schema now; tool calls occur in "
            "later turns.\n" + catalogue
        ),
    }
    position = 1 if messages and messages[0]["role"] == "system" else 0
    messages.insert(position, context)
    return messages
