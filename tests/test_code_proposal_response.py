import json

import pytest
from pydantic import ValidationError

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateProposal,
    CodeTemplateRequest,
)
from edcraft_validator.domains.code.prompt_builder import build_code_generation_request
from edcraft_validator.domains.code.proposal_response import CodeProposalResponse
from edcraft_validator.llm.llm_contracts import PlannedGenerationResponse


def response_with_parameter(kind: str, values: list[object]) -> dict[str, object]:
    return {
        "question_template": "What does inspect({value}) return?",
        "code": "def inspect(value):\n    return value",
        "entry_function": "inspect",
        "parameters": [{"name": "value", "kind": kind, "values": values}],
        "answer_target": "return_value",
        "answer_expression": "value",
        "distractors": [
            {"expression": "value + 1", "reason_template": "Adds one."},
            {"expression": "value - 1", "reason_template": "Subtracts one."},
        ],
    }


def test_generation_request_uses_one_typed_response_contract() -> None:
    request = build_code_generation_request(
        CodeTemplateRequest(
            prompt="Create a question about arithmetic", difficulty="beginner"
        )
    )

    assert request.response_model == PlannedGenerationResponse[CodeProposalResponse]
    assert request.prompt_version == "code-template-v9+response-v3"
    assert request.offered_tool_names
    assert "Create a question about arithmetic" in request.messages[1]["content"]
    assert "Use native JSON values" in request.messages[1]["content"]
    assert (
        "Do not encode numbers, booleans, or arrays as strings"
        in request.messages[1]["content"]
    )


def test_free_form_prompt_agrees_with_the_typed_response_schema() -> None:
    request = build_code_generation_request(
        CodeTemplateRequest(
            prompt="Create a question with a boolean parameter", difficulty="beginner"
        )
    )
    user_prompt = request.messages[1]["content"]

    assert "booleans use JSON booleans" in user_prompt
    schema = request.response_model.model_json_schema()
    response_schema = schema["$defs"]["CodeProposalResponse"]
    parameter_items = response_schema["properties"]["parameters"]["items"]
    assert len(parameter_items["anyOf"]) == 4
    boolean_values = schema["$defs"]["BooleanParameterResponse"]["properties"]["values"]
    assert boolean_values["items"] == {"type": "boolean"}


@pytest.mark.parametrize(
    ("kind", "values"),
    [
        ("integer", [-2, 3]),
        ("boolean", [True, False]),
        ("string", ["plain text", "false"]),
        ("integer_list", [[1, 2], [-3, 4]]),
    ],
)
def test_response_schema_accepts_native_values(kind: str, values: list[object]) -> None:
    proposal = CodeProposalResponse.model_validate_json(
        json.dumps(response_with_parameter(kind, values))
    )

    assert isinstance(proposal, CodeTemplateProposal)
    assert proposal.parameters[0].values == values


def test_response_schema_rejects_malformed_json() -> None:
    with pytest.raises(ValidationError, match="Invalid JSON"):
        CodeProposalResponse.model_validate_json('{"code":')


@pytest.mark.parametrize(
    ("kind", "values"),
    [
        ("integer", ["1", "2"]),
        ("boolean", ["true", "false"]),
        ("string", [True, False]),
        ("integer_list", ["[1,2]", "[3,4]"]),
        ("integer_list", [[1, True], [2]]),
    ],
)
def test_response_schema_rejects_values_that_do_not_match_kind(
    kind: str, values: list[object]
) -> None:
    with pytest.raises(ValidationError):
        CodeProposalResponse.model_validate_json(
            json.dumps(response_with_parameter(kind, values))
        )


def test_response_schema_rejects_duplicate_typed_values() -> None:
    with pytest.raises(ValidationError, match="parameter values must be unique"):
        CodeProposalResponse.model_validate(response_with_parameter("integer", [2, 2]))


def test_combined_response_requires_a_nonempty_unique_check_plan() -> None:
    response_model = PlannedGenerationResponse[CodeProposalResponse]
    payload = {"proposal": response_with_parameter("integer", [1, 2]), "checks": []}

    with pytest.raises(ValidationError):
        response_model.model_validate(payload)

    payload["checks"] = [
        {"name": "code_execution", "arguments": {}},
        {"name": "code_execution", "arguments": {}},
    ]
    with pytest.raises(ValidationError, match="must be unique"):
        response_model.model_validate(payload)
