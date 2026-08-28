from types import SimpleNamespace

import pytest

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.openai import (
    OpenAICompatibleQuestionGenerator,
    OpenAIGenerationError,
    OpenAIInput,
    OpenAIJsonValue,
    OpenAIQuestionDraftResponse,
    _api_key,
    _base_url,
)
from edcraft_validator.models import ValidationIssue, ValidationReport


def api_question() -> OpenAIQuestionDraftResponse:
    """Return a parsed response shaped like the co-generation contract."""
    return OpenAIQuestionDraftResponse(
        code="def square(x):\n    return x * x",
        entry_function="square",
        inputs=[
            OpenAIInput(
                name="x",
                value=OpenAIJsonValue(kind="scalar", scalar=4, items=[], properties=[]),
            )
        ],
        question="What does square(4) return?",
        distractors=[
            OpenAIJsonValue(kind="scalar", scalar=value, items=[], properties=[])
            for value in [4, 8, 20]
        ],
        distractor_reasons=["Confuses input", "Adds instead", "Adds four"],
        question_type="mcq",
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


def client_with(parsed: OpenAIQuestionDraftResponse | None) -> SimpleNamespace:
    content = parsed.model_dump_json() if parsed is not None else None
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


def test_generates_draft_using_json_output() -> None:
    client = client_with(api_question())
    generator = OpenAICompatibleQuestionGenerator("openai", client, model="test-model")
    request = GenerationRequest(topic="arithmetic", difficulty="beginner")

    draft = generator.generate_draft(request)

    assert draft.entry_function == "square"
    assert client.chat.completions.arguments["model"] == "test-model"
    assert client.chat.completions.arguments["response_format"] == {
        "type": "json_object"
    }


def test_includes_validation_feedback_in_retry_prompt() -> None:
    client = client_with(api_question())
    generator = OpenAICompatibleQuestionGenerator("openai", client, model="test-model")
    feedback = ValidationReport(
        status="invalid",
        actual_answer=25,
        issues=[
            ValidationIssue(
                code="WRONG_PROPOSED_ANSWER",
                message="The proposed answer is incorrect",
            )
        ],
    )

    generator.generate_draft(
        GenerationRequest(topic="arithmetic", difficulty="intermediate"),
        feedback=feedback,
    )

    user_prompt = client.chat.completions.arguments["messages"][1]["content"]
    assert "WRONG_PROPOSED_ANSWER" in user_prompt
    assert "25" not in user_prompt
    assert "exactly 3 distractors" in user_prompt


def test_reports_missing_parsed_response() -> None:
    generator = OpenAICompatibleQuestionGenerator(
        "openai", client_with(None), model="test-model"
    )

    with pytest.raises(OpenAIGenerationError, match="invalid question JSON"):
        generator.generate_draft(
            GenerationRequest(topic="arithmetic", difficulty="beginner")
        )


def test_provider_uses_provider_specific_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("SOCLAAS_API_KEY", "soclaas-key")
    monkeypatch.setenv("SOCLAAS_BASE_URL", "https://soclaas.example/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")

    assert _api_key("openai") == "openai-key"
    assert _base_url("openai") == "https://openai.example/v1"
    assert _api_key("soclaas") == "soclaas-key"
    assert _base_url("soclaas") == "https://soclaas.example/v1"
