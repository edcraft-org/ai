"""Provider-neutral planning context and callable tool schemas."""

import copy
import json
from functools import lru_cache, reduce
from operator import or_
from typing import Any, Literal

from pydantic import Field, create_model

from edcraft_validator.llm.llm_contracts import (
    CheckPlanResponse,
    RecommendedCheck,
    RecommendedCheckArguments,
    StructuredGenerationRequest,
)


@lru_cache(maxsize=32)
def constrained_check_plan(
    response_model,
    offered_names: tuple[str, ...],
    argument_models: tuple = (),
):
    """Constrain each offered name to its closed, typed planning arguments."""
    if not issubclass(response_model, CheckPlanResponse):
        return response_model
    if not offered_names:
        raise ValueError("a check plan requires offered tools")
    models = dict(argument_models)
    checks = tuple(
        create_model(
            f"CatalogueCheck_{name}",
            __base__=RecommendedCheck,
            name=(Literal[name], ...),
            arguments=(models.get(name, RecommendedCheckArguments), ...),
        )
        for name in offered_names
    )
    check = reduce(or_, checks)
    return create_model(
        f"Catalogue{response_model.__name__}",
        __base__=response_model,
        checks=(list[check], Field(min_length=1)),
    )


def generation_messages(request: StructuredGenerationRequest) -> list[dict[str, Any]]:
    """Offer purposes and only model-owned argument schemas at planning time."""
    messages = [message.copy() for message in request.messages]
    if not request.tool_catalogue:
        return messages
    models = dict(request.check_argument_models)
    catalogue = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "arguments_schema": models.get(
                tool["name"], RecommendedCheckArguments
            ).model_json_schema(),
        }
        for tool in request.tool_catalogue.definitions()
    ]
    context = {
        "role": "system",
        "content": (
            "Available validation checks follow as JSON. "
            "Select checks by their names and descriptions. "
            "Return the response matching the supplied schema with each selected "
            "check's model-owned arguments. Use {} when its arguments schema is empty. "
            "The application freezes names and arguments, supplies the current "
            "candidate and request-owned values, and executes the checks directly. "
            "Do not supply application-owned values or request native tool calls.\n"
            + json.dumps(catalogue)
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
