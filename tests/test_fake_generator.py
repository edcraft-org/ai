from pathlib import Path

import pytest

from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.models import GenerationRequest

EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


@pytest.mark.parametrize(
    ("topic", "entry_function"),
    [
        ("arithmetic", "square"),
        ("conditionals", "delivery_fee"),
        ("loops", "accumulated_bonus"),
        ("functions", "weighted_total"),
        ("lists", "summarize"),
    ],
)
def test_selects_example_for_topic(topic: str, entry_function: str) -> None:
    request = GenerationRequest.model_validate(
        {"topic": topic, "difficulty": "intermediate"}
    )

    draft = FakeQuestionGenerator(EXAMPLES_DIR).generate_draft(request)

    assert draft.entry_function == entry_function
    assert len(draft.distractors) == 3


def test_uses_requested_distractor_count() -> None:
    request = GenerationRequest(
        topic="arithmetic",
        difficulty="beginner",
        num_distractors=2,
    )

    draft = FakeQuestionGenerator(EXAMPLES_DIR).generate_draft(request)

    assert len(draft.distractors) == 2


def test_missing_example_is_reported() -> None:
    request = GenerationRequest(topic="arithmetic", difficulty="beginner")
    with pytest.raises(FileNotFoundError):
        FakeQuestionGenerator(Path("missing-examples")).generate_draft(request)
