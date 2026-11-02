"""Planning schemas expose only model-owned arguments, across domains and providers."""


def test_planning_schema_pairs_each_tool_with_its_own_closed_arguments():
    import pytest
    from pydantic import ValidationError

    from edcraft_validator.domains.code.check_plan import CODE_CHECK_ARGUMENT_MODELS
    from edcraft_validator.llm.llm_contracts import CheckPlanResponse
    from edcraft_validator.llm.tool_context import constrained_check_plan

    model = constrained_check_plan(
        CheckPlanResponse,
        (
            "code_require_features",
            "code_verify_template_structure",
            "code_assess_template_relevance",
        ),
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
            "name": "code_assess_template_relevance",
            "arguments": {"author_request": "changed"},
        },
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


def test_check_plan_rejects_empty_duplicate_and_unexpected_fields():
    import pytest
    from pydantic import ValidationError

    from edcraft_validator.llm.llm_contracts import CheckPlanResponse

    check = {"name": "check", "arguments": {}}
    for payload in [
        {"checks": []},
        {"checks": [check, check]},
        {"checks": [check], "unexpected": {}},
    ]:
        with pytest.raises(ValidationError):
            CheckPlanResponse.model_validate(payload)
