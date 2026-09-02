import os

import pytest

from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.openai import OpenAITemplateGenerator

pytestmark = pytest.mark.openai_live


def test_real_openai_template_authoring() -> None:
    """Exercise the configured OpenAI model before submitting a PR."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    proposal = OpenAITemplateGenerator().generate_proposal(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
    )

    assert proposal.code
    assert proposal.answer_expression
    assert len(proposal.distractors) == 3
    assert [parameter.name for parameter in proposal.parameters] in [
        ["a", "b"],
        ["a", "b", "c"],
    ]
    assert all(parameter.kind == "integer" for parameter in proposal.parameters)
