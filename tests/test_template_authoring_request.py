import pytest
from pydantic import ValidationError

from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplateProviderSelection,
)


def test_template_request_defaults_to_three_distractors() -> None:
    request = TemplateAuthoringRequest(topic="loops", difficulty="beginner")

    assert request.num_distractors == 3


@pytest.mark.parametrize("count", [0, 1, 4])
def test_template_request_rejects_unsupported_distractor_count(count: int) -> None:
    with pytest.raises(ValidationError):
        TemplateAuthoringRequest(
            topic="loops", difficulty="beginner", num_distractors=count
        )


def test_template_request_rejects_unknown_topic() -> None:
    with pytest.raises(ValidationError):
        TemplateAuthoringRequest.model_validate(
            {"topic": "graphs", "difficulty": "beginner"}
        )


def test_provider_selection_strips_explicit_values() -> None:
    selection = TemplateProviderSelection(
        provider=" ollama ", model=" qwen2.5-coder:14b "
    )

    assert selection.provider == "ollama"
    assert selection.model == "qwen2.5-coder:14b"


@pytest.mark.parametrize("field", ["provider", "model"])
def test_provider_selection_rejects_blank_values(field: str) -> None:
    values = {"provider": "ollama", "model": "qwen"}
    values[field] = "  "

    with pytest.raises(ValidationError):
        TemplateProviderSelection.model_validate(values)
