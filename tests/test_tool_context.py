"""Model schemas expose only callable arguments, across domains and providers."""

import copy

from jsonschema import Draft202012Validator

from edcraft_validator.llm.tool_context import callable_tool


def test_callable_schema_retains_nested_and_recursive_argument_definitions():
    definition = {
        "name": "example_check",
        "description": "Check a supplied feature tree",
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidate": {"$ref": "#/$defs/Candidate"},
                "required": {"$ref": "#/$defs/Features"},
            },
            "required": ["candidate", "required"],
            "$defs": {
                "Candidate": {"type": "object"},
                "Features": {"type": "array", "items": {"$ref": "#/$defs/Feature"}},
                "Feature": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"$ref": "#/$defs/Feature"}},
                    ]
                },
            },
        },
    }
    original = copy.deepcopy(definition)
    tool = callable_tool(definition, {"candidate": {}})
    schema = tool["function"]["parameters"]
    assert set(schema["$defs"]) == {"Features", "Feature"}
    assert schema["required"] == ["required"]
    Draft202012Validator(schema).validate({"required": ["loop", ["helper"]]})
    assert definition == original
