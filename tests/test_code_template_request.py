import pytest
from pydantic import ValidationError

from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection


def test_template_request_defaults_to_three_distractors() -> None:
    request = CodeTemplateRequest(
        prompt="Create a question about loops", difficulty="beginner"
    )

    assert request.num_distractors == 3


@pytest.mark.parametrize("count", [0, 1, 4])
def test_template_request_rejects_unsupported_distractor_count(count: int) -> None:
    with pytest.raises(ValidationError):
        CodeTemplateRequest(
            prompt="Create a question about loops",
            difficulty="beginner",
            num_distractors=count,
        )


@pytest.mark.parametrize("prompt", ["", "   "])
def test_template_request_rejects_blank_prompt(prompt: str) -> None:
    with pytest.raises(ValidationError):
        CodeTemplateRequest(prompt=prompt, difficulty="beginner")


@pytest.mark.parametrize("difficulty", ["beginner", "intermediate", "advanced"])
def test_template_request_accepts_original_difficulty_labels(difficulty: str) -> None:
    request = CodeTemplateRequest.model_validate(
        {"prompt": "Create a graph traversal question", "difficulty": difficulty}
    )

    assert request.difficulty == difficulty


def test_template_request_accepts_topics_outside_the_old_catalogue() -> None:
    request = CodeTemplateRequest(
        prompt="Create a question about graph traversal", difficulty="advanced"
    )

    assert "graph traversal" in request.prompt


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
