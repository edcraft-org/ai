import os

import pytest

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.openai import OpenAIQuestionGenerator

pytestmark = pytest.mark.openai_live


def test_real_openai_generation() -> None:
    """Exercise the configured OpenAI model before submitting a PR."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    draft = OpenAIQuestionGenerator().generate_draft(
        GenerationRequest(topic="arithmetic", difficulty="beginner")
    )

    assert draft.code
    assert draft.entry_function
    assert len(draft.distractors) == 3
    assert len(draft.distractor_reasons) == 3
