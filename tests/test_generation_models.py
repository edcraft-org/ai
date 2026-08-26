import pytest
from pydantic import ValidationError

from edcraft_validator.generation.models import GenerationRequest


def test_generation_request_defaults_to_three_distractors() -> None:
    request = GenerationRequest(topic="loops", difficulty="intermediate")
    assert request.num_distractors == 3


@pytest.mark.parametrize("num_distractors", [1, 4])
def test_generation_request_rejects_unsupported_distractor_count(
    num_distractors: int,
) -> None:
    with pytest.raises(ValidationError):
        GenerationRequest(
            topic="loops",
            difficulty="intermediate",
            num_distractors=num_distractors,
        )


def test_generation_request_rejects_unknown_topic() -> None:
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(
            {"topic": "networking", "difficulty": "beginner"}
        )

