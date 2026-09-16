import json

import pytest
from pydantic import ValidationError

from edcraft_validator.domains.code.authoring import (
    CodeProposalResponse,
    build_code_generation_request,
    parse_code_proposal_response,
)
from edcraft_validator.domains.code.models import CodeTemplateRequest


def response_with_parameter(kind: str, values: list[str]) -> dict[str, object]:
    return {
        "code": "def inspect(value):\n    return value",
        "entry_function": "inspect",
        "parameters": [{"name": "value", "kind": kind, "values": values}],
        "answer_expression": "value",
        "distractors": [
            {"expression": "value + 1", "reason_template": "Adds one."},
            {"expression": "value - 1", "reason_template": "Subtracts one."},
        ],
    }


def test_generation_request_uses_one_provider_independent_response_contract() -> None:
    request = build_code_generation_request(
        CodeTemplateRequest(topic="arithmetic", difficulty="beginner")
    )

    assert request.response_model is CodeProposalResponse
    assert request.parse_response is parse_code_proposal_response
    assert request.prompt_version == "code-template-v8+response-v1"
    assert "Use strings for every item" in request.messages[1]["content"]


def test_boolean_profile_prompt_agrees_with_the_string_response_schema() -> None:
    request = build_code_generation_request(
        CodeTemplateRequest(topic="conditionals", difficulty="beginner")
    )
    system_prompt = request.messages[0]["content"]
    user_prompt = request.messages[1]["content"]

    assert "Use JSON booleans" not in system_prompt
    assert 'booleans use "true" or "false"' in user_prompt


@pytest.mark.parametrize(
    ("kind", "wire_values", "canonical_values"),
    [
        ("integer", ["-2", "+3"], [-2, 3]),
        ("boolean", ["true", "FALSE"], [True, False]),
        ("string", ["plain text", "false"], ["plain text", "false"]),
        ("integer_list", ["[1,2]", "[-3, 4]"], [[1, 2], [-3, 4]]),
    ],
)
def test_response_parser_converts_each_parameter_kind(
    kind: str, wire_values: list[str], canonical_values: list[object]
) -> None:
    proposal = parse_code_proposal_response(
        json.dumps(response_with_parameter(kind, wire_values))
    )

    assert proposal.parameters[0].values == canonical_values


def test_response_parser_rejects_malformed_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_code_proposal_response('{"code":')


def test_response_parser_rejects_values_outside_the_string_wire_schema() -> None:
    response = response_with_parameter("integer", ["1", "2"])
    response["parameters"][0]["values"] = [1, 2]

    with pytest.raises(ValidationError, match="Input should be a valid string"):
        parse_code_proposal_response(json.dumps(response))


@pytest.mark.parametrize(
    ("kind", "values", "message"),
    [
        ("integer", ["1.5", "2"], "invalid integer"),
        ("boolean", ["yes", "false"], "invalid boolean"),
        ("integer_list", ["[1,true]", "[2]"], "invalid integer_list"),
    ],
)
def test_response_parser_rejects_invalid_value_encodings(
    kind: str, values: list[str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_code_proposal_response(json.dumps(response_with_parameter(kind, values)))
