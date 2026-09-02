from types import SimpleNamespace

import pytest

from edcraft_validator.domains.code.templates import CodeTemplateProposal
from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.openai import (
    OpenAICompatibleTemplateGenerator,
    OpenAIGenerationError,
    _api_key,
    _base_url,
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


def test_generates_template_using_strict_structured_outputs() -> None:
    client = client_with(code_proposal())
    generator = OpenAICompatibleTemplateGenerator("openai", client, model="test-model")

    result = generator.generate_proposal(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
    )

    assert result.entry_function == "calculate"
    assert client.chat.completions.arguments["model"] == "test-model"
    response_format = client.chat.completions.arguments["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "question_template"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert "topic" not in schema["properties"]
    assert "question_template" not in schema["properties"]
    messages = client.chat.completions.arguments["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "answer_target=return_value" in messages[1]["content"]


def test_reports_empty_template_response() -> None:
    generator = OpenAICompatibleTemplateGenerator(
        "openai", client_with(None), model="test-model"
    )

    with pytest.raises(OpenAIGenerationError, match="failed to generate"):
        generator.generate_proposal(
            TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
        )


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
