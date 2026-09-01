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
    # OpenAI-compatible providers must request and parse a JSON object response.
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
    # Retry prompts should include actionable issue codes without leaking answers.
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
    # Empty provider content must become a clear generation error.
    generator = OpenAICompatibleQuestionGenerator(
        "openai", client_with(None), model="test-model"
    )

    with pytest.raises(OpenAIGenerationError, match="invalid question JSON"):
        generator.generate_draft(
            GenerationRequest(topic="arithmetic", difficulty="beginner")
        )


def test_converts_nested_tagged_values_to_python_values() -> None:
    nested = OpenAIQuestionDraftResponse(
        code="def total(values):\n    return sum(values)",
        entry_function="total",
        inputs=[
            OpenAIInput(
                name="values",
                value=OpenAIJsonValue(
                    kind="list",
                    scalar=None,
                    items=[
                        OpenAIJsonValue(
                            kind="scalar", scalar=value, items=[], properties=[]
                        )
                        for value in [1, 2, 3]
                    ],
                    properties=[],
                ),
            )
        ],
        question="What does total([1, 2, 3]) return?",
        distractors=[
            OpenAIJsonValue(kind="scalar", scalar=value, items=[], properties=[])
            for value in [3, 5, 7]
        ],
        distractor_reasons=["reason"] * 3,
        question_type="mcq",
    )

    generator = OpenAICompatibleQuestionGenerator(
        "openai", client_with(nested), model="test-model"
    )

    draft = generator.generate_draft(
        GenerationRequest(topic="lists", difficulty="beginner")
    )

    assert draft.inputs == {"values": [1, 2, 3]}


def test_accepts_tagged_list_form_for_inputs() -> None:
    response = api_question().model_dump()
    response["inputs"] = {
        "kind": "list",
        "scalar": None,
        "items": [
            {
                "kind": "object",
                "scalar": None,
                "items": [],
                "properties": [
                    {
                        "key": "name",
                        "value": {
                            "kind": "scalar",
                            "scalar": "x",
                            "items": [],
                            "properties": [],
                        },
                    },
                    {
                        "key": "value",
                        "value": {
                            "kind": "scalar",
                            "scalar": 4,
                            "items": [],
                            "properties": [],
                        },
                    },
                ],
            }
        ],
        "properties": [],
    }
    parsed = OpenAIQuestionDraftResponse.model_validate(response)

    assert parsed.to_draft().inputs == {"x": 4}


def test_provider_uses_provider_specific_configuration(monkeypatch) -> None:
    # OpenAI and SocLaas must read only their own credentials and base URLs.
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("SOCLAAS_API_KEY", "soclaas-key")
    monkeypatch.setenv("SOCLAAS_BASE_URL", "https://soclaas.example/v1")

    assert _api_key("openai") == "openai-key"
    assert _base_url("openai") == "https://openai.example/v1"
    assert _api_key("soclaas") == "soclaas-key"
    assert _base_url("soclaas") == "https://soclaas.example/v1"
