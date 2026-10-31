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


def test_planning_schema_pairs_each_tool_with_its_own_closed_arguments():
    import pytest
    from pydantic import ValidationError

    from edcraft_validator.domains.code.check_plan import CODE_CHECK_ARGUMENT_MODELS
    from edcraft_validator.llm.llm_contracts import CheckPlanResponse
    from edcraft_validator.llm.tool_context import constrained_check_plan

    model = constrained_check_plan(
        CheckPlanResponse,
        ("code_require_features", "code_verify_template_structure"),
        CODE_CHECK_ARGUMENT_MODELS,
    )
    valid = {
        "checks": [
            {"name": "code_require_features", "arguments": {"required": ["loop"]}},
            {"name": "code_verify_template_structure", "arguments": {}},
        ]
    }
    assert model.model_validate(valid).checks[0].arguments.required == ["loop"]
    for check in [
        {"name": "code_require_features", "arguments": {}},
        {"name": "code_verify_template_structure", "arguments": {"required": ["loop"]}},
        {"name": "invented", "arguments": {}},
        {
            "name": "code_require_features",
            "arguments": {"required": ["loop"], "candidate": {}},
        },
    ]:
        with pytest.raises(ValidationError):
            model.model_validate({"checks": [check]})
    schema = model.model_json_schema()
    assert "candidate" not in str(schema)
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node.get("required", [])) == set(node["properties"])
