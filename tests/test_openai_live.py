import os

import pytest

from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.openai import OpenAITemplateGenerator

pytestmark = pytest.mark.openai_live


def test_real_openai_template_authoring() -> None:
    """Exercise the configured OpenAI model before submitting a PR."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    template = OpenAITemplateGenerator().generate_template(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
    )

    assert template.topic == "arithmetic"
    assert template.difficulty == "beginner"
    assert template.code
    assert template.answer_expression
    assert len(template.distractors) == 3
