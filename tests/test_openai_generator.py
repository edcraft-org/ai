import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from edcraft_validator.domains.code.authoring import build_code_generation_request
from edcraft_validator.domains.code.models import CodeTemplateAuthoringRequest
from edcraft_validator.domains.code.templates import CodeTemplateProposal
from edcraft_validator.generation.base import (
    GenerationSchemaError,
    StructuredGenerationRequest,
)
from edcraft_validator.generation.openai import (
    OpenAICompatibleProvider,
    OpenAIGenerationError,
    _api_key,
    _base_url,
    _max_retries,
    _model,
    _timeout_seconds,
)


def generation_request(topic: str = "arithmetic", difficulty: str = "beginner"):
    return build_code_generation_request(
        CodeTemplateAuthoringRequest(topic=topic, difficulty=difficulty),
        provider="openai",
    )


def code_proposal() -> CodeTemplateProposal:
    return CodeTemplateProposal.model_validate(
        {
            "code": "def calculate(a, b):\n    return a + b",
            "entry_function": "calculate",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [3, 4]},
            ],
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a - b", "reason_template": "Subtracts b."},
                {"expression": "a * b", "reason_template": "Multiplies."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
                {"expression": "a + b + 2", "reason_template": "Adds two."},
            ],
        }
    )


class RecordingCompletions:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.arguments: dict[str, object] = {}

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.arguments = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def client_with(proposal: CodeTemplateProposal | None) -> SimpleNamespace:
    content = proposal.model_dump_json() if proposal is not None else None
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


def client_with_content(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


def test_generates_template_using_strict_structured_outputs() -> None:
    client = client_with(code_proposal())
    provider = OpenAICompatibleProvider("openai", client, model="test-model")

    result = provider.generate(generation_request())

    assert result.entry_function == "calculate"
    assert client.chat.completions.arguments["model"] == "test-model"
    response_format = client.chat.completions.arguments["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "template_proposal"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert "topic" not in schema["properties"]
    assert "question_template" not in schema["properties"]
    messages = client.chat.completions.arguments["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "answer_target=return_value" in messages[1]["content"]
    assert "exactly 3 distractor candidates" in messages[1]["content"]


def test_provider_accepts_a_schema_from_another_domain() -> None:
    class ExampleProposal(BaseModel):
        equation: str

    client = client_with_content('{"equation":"x + 1"}')
    provider = OpenAICompatibleProvider("openai", client, model="test-model")
    request = StructuredGenerationRequest(
        messages=[{"role": "user", "content": "Create an equation"}],
        response_model=ExampleProposal,
        parse_response=ExampleProposal.model_validate_json,
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
    payload = code_proposal().model_dump(mode="json")
    payload["parameters"][0]["values"] = [2, 2]
    provider = OpenAICompatibleProvider(
        "openai", client_with_content(json.dumps(payload)), model="test-model"
    )

    with pytest.raises(
        GenerationSchemaError, match="parameter values must be unique"
    ) as error:
        provider.generate(generation_request())

    assert error.value.category == "schema_validation"


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


def test_openai_prompt_metadata_is_stable() -> None:
    request = generation_request("functions", "intermediate")

    first = request.prompt_metadata()
    second = request.prompt_metadata()

    assert first == second
    assert first.version == "code-template-v8"
    assert len(first.sha256) == 64
    assert (
        first.sha256
        != generation_request("functions", "advanced").prompt_metadata().sha256
    )


def test_openai_client_uses_bounded_timeout_and_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("edcraft_validator.generation.openai.OpenAI", RecordingOpenAI)
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
