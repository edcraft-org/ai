from types import SimpleNamespace

import pytest

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.openai import (
    OpenAIGenerationError,
    OpenAIInput,
    OpenAIJsonValue,
    OpenAIQuestionGenerator,
    OpenAIQuestionResponse,
)
from edcraft_validator.models import ValidationIssue, ValidationReport


def api_question() -> OpenAIQuestionResponse:
    """Return a parsed response shaped like a real Structured Output."""
    return OpenAIQuestionResponse(
        code="def square(x):\n    return x * x",
        entry_function="square",
        inputs=[
            OpenAIInput(
                name="x",
                value=OpenAIJsonValue(kind="scalar", scalar=4, items=[], properties=[]),
            )
        ],
        question="What does square(4) return?",
        proposed_answer=OpenAIJsonValue(
            kind="scalar", scalar=16, items=[], properties=[]
        ),
        distractors=[
            OpenAIJsonValue(kind="scalar", scalar=value, items=[], properties=[])
            for value in [4, 8, 20]
        ],
        question_type="mcq",
    )


class RecordingResponses:
    def __init__(self, output_parsed: OpenAIQuestionResponse | None) -> None:
        self.output_parsed = output_parsed
        self.arguments: dict[str, object] = {}

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.arguments = kwargs
        return SimpleNamespace(output_parsed=self.output_parsed)


def client_with(parsed: OpenAIQuestionResponse | None) -> SimpleNamespace:
    return SimpleNamespace(responses=RecordingResponses(parsed))


def test_generates_question_using_structured_outputs() -> None:
    client = client_with(api_question())
    generator = OpenAIQuestionGenerator(client, model="test-model")
    request = GenerationRequest(topic="arithmetic", difficulty="beginner")

    question = generator.generate(request)

    assert question.entry_function == "square"
    assert question.proposed_answer == 16
    assert client.responses.arguments["model"] == "test-model"
    assert client.responses.arguments["text_format"] is OpenAIQuestionResponse


def test_includes_validation_feedback_in_retry_prompt() -> None:
    client = client_with(api_question())
    generator = OpenAIQuestionGenerator(client, model="test-model")
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

    generator.generate(
        GenerationRequest(topic="arithmetic", difficulty="intermediate"),
        feedback=feedback,
    )

    user_prompt = client.responses.arguments["input"][1]["content"]
    assert "WRONG_PROPOSED_ANSWER" in user_prompt
    assert "25" in user_prompt


def test_reports_missing_parsed_response() -> None:
    generator = OpenAIQuestionGenerator(client_with(None), model="test-model")

    with pytest.raises(OpenAIGenerationError, match="no parsed question"):
        generator.generate(GenerationRequest(topic="arithmetic", difficulty="beginner"))
