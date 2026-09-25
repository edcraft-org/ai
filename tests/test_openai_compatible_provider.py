import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.prompt_builder import build_code_generation_request
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationSchemaError,
)
from edcraft_validator.llm.openai_compatible_provider import (
    OpenAICompatibleProvider,
    OpenAIGenerationError,
    _api_key,
    _base_url,
    _max_retries,
    _model,
    _timeout_seconds,
)


def generation_request(
    prompt: str = "Create an arithmetic question", difficulty: str = "beginner"
):
    return build_code_generation_request(
        CodeTemplateRequest(prompt=prompt, difficulty=difficulty)
    )


def code_response() -> dict[str, object]:
    return {
        "proposal": {
            "question_template": "What does calculate({a}, {b}) return?",
            "code": "def calculate(a, b):\n    return a + b",
            "entry_function": "calculate",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [3, 4]},
            ],
            "answer_target": "return_value",
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a - b", "reason_template": "Subtracts b."},
                {"expression": "a * b", "reason_template": "Multiplies."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
            ],
        },
        "checks": [
            {"name": "code_execution", "arguments": {}},
        ],
    }


class RecordingCompletions:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.arguments: dict[str, object] = {}

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.arguments = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def client_with(response: dict[str, object] | None) -> SimpleNamespace:
    content = json.dumps(response) if response is not None else None
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


def client_with_content(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_generates_template_using_strict_structured_outputs(provider_name) -> None:
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test-model")

    result = provider.generate(generation_request())

    assert result.proposal.entry_function == "calculate"
    assert result.proposal.parameters[0].values == [1, 2]
    assert result.checks[0].name == "code_execution"
    assert client.chat.completions.arguments["model"] == "test-model"
    response_format = client.chat.completions.arguments["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == (
        "template_proposal_and_check_plan"
    )
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]) == {"proposal", "checks"}
    proposal_schema = schema["$defs"]["CodeProposalResponse"]
    assert "question_template" in proposal_schema["properties"]
    assert "answer_target" in proposal_schema["properties"]
    parameter_items = proposal_schema["properties"]["parameters"]["items"]
    assert len(parameter_items["anyOf"]) == 4
    integer_schema = schema["$defs"]["IntegerParameterResponse"]
    assert integer_schema["properties"]["values"]["items"] == {"type": "integer"}
    check_schema = schema["$defs"]["RecommendedCheck"]
    assert set(check_schema["required"]) == set(check_schema["properties"])
    arguments_schema = schema["$defs"]["RecommendedCheckArguments"]
    assert arguments_schema["additionalProperties"] is False
    assert arguments_schema["properties"] == {}
    messages = client.chat.completions.arguments["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "Create an arithmetic question" in messages[1]["content"]
    assert "at least 3 distractor candidates" in messages[1]["content"]
    assert "Use native JSON values" in messages[1]["content"]


def test_provider_accepts_a_schema_from_another_domain() -> None:
    class ExampleProposal(BaseModel):
        equation: str

    client = client_with_content('{"equation":"x + 1"}')
    provider = OpenAICompatibleProvider("openai", client, model="test-model")
    request = StructuredGenerationRequest(
        messages=[{"role": "user", "content": "Create an equation"}],
        response_model=ExampleProposal,
        prompt_version="example-v1",
    )

    result = provider.generate(request)

    assert result == ExampleProposal(equation="x + 1")
    schema = client.chat.completions.arguments["response_format"]["json_schema"]
    assert "equation" in schema["schema"]["properties"]


def test_reports_empty_template_response() -> None:
    provider = OpenAICompatibleProvider("openai", client_with(None), model="test-model")

    with pytest.raises(
        OpenAIGenerationError, match="returned an empty response"
    ) as error:
        provider.generate(generation_request())

    assert error.value.category == "invalid_response"


def test_reports_duplicate_parameter_values_as_schema_error() -> None:
    payload = code_response()
    payload["proposal"]["parameters"][0]["values"] = [2, 2]
    provider = OpenAICompatibleProvider(
        "openai", client_with_content(json.dumps(payload)), model="test-model"
    )

    with pytest.raises(
        GenerationSchemaError, match="parameter values must be unique"
    ) as error:
        provider.generate(generation_request())

    assert error.value.category == "schema_validation"


def test_reports_parameter_type_mismatch_as_schema_error() -> None:
    payload = code_response()
    payload["proposal"]["parameters"][0]["values"] = ["not-an-int", "2"]
    provider = OpenAICompatibleProvider(
        "openai", client_with_content(json.dumps(payload)), model="test-model"
    )

    with pytest.raises(GenerationSchemaError, match="local schema validation") as error:
        provider.generate(generation_request())

    assert error.value.category == "schema_validation"


def test_reports_malformed_json_as_response_error() -> None:
    class ExampleProposal(BaseModel):
        equation: str

    provider = OpenAICompatibleProvider(
        "openai", client_with_content('{"equation":'), model="test-model"
    )

    with pytest.raises(GenerationResponseError, match="malformed JSON") as error:
        provider.generate(
            StructuredGenerationRequest(
                messages=[{"role": "user", "content": "Create an equation"}],
                response_model=ExampleProposal,
                prompt_version="example-v1",
            )
        )

    assert error.value.category == "invalid_response"


def test_provider_uses_provider_specific_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("SOCLAAS_API_KEY", "soclaas-key")
    monkeypatch.setenv("SOCLAAS_BASE_URL", "https://soclaas.example/v1")

    assert _api_key("openai") == "openai-key"
    assert _base_url("openai") == "https://openai.example/v1"
    assert _api_key("soclaas") == "soclaas-key"
    assert _base_url("soclaas") == "https://soclaas.example/v1"


def test_provider_configuration_strips_surrounding_whitespace(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "  openai-key\n")
    monkeypatch.setenv("OPENAI_BASE_URL", " https://openai.example/v1/ \n")

    assert _api_key("openai") == "openai-key"
    assert _base_url("openai") == "https://openai.example/v1/"


def test_provider_configuration_rejects_internal_whitespace(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key\nsecond-line")

    with pytest.raises(OpenAIGenerationError, match="invalid whitespace"):
        _api_key("openai")


def test_soclaas_requires_its_own_model(monkeypatch) -> None:
    monkeypatch.delenv("SOCLAAS_MODEL", raising=False)

    with pytest.raises(OpenAIGenerationError, match="SOCLAAS_MODEL is not configured"):
        _model("soclaas")


def test_openai_client_uses_bounded_timeout_and_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "edcraft_validator.llm.openai_compatible_provider.OpenAI", RecordingOpenAI
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")

    provider = OpenAICompatibleProvider("openai")

    assert provider.model
    assert captured["timeout"] == 45
    assert captured["max_retries"] == 0


@pytest.mark.parametrize(
    ("variable", "value", "reader", "message"),
    [
        ("OPENAI_TIMEOUT_SECONDS", "0", _timeout_seconds, "greater than zero"),
        ("OPENAI_TIMEOUT_SECONDS", "slow", _timeout_seconds, "must be a number"),
        ("OPENAI_MAX_RETRIES", "-1", _max_retries, "between 0 and 5"),
        ("OPENAI_MAX_RETRIES", "many", _max_retries, "must be an integer"),
    ],
)
def test_openai_rejects_invalid_request_bounds(
    monkeypatch, variable, value, reader, message
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(OpenAIGenerationError, match=message):
        reader("openai")
