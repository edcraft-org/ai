import pytest
from pydantic import ValidationError

from edcraft_validator.generation.models import TemplateAuthoringRequest


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
