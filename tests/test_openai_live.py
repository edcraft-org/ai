import os

import pytest

from edcraft_validator.application import TemplateApplication
from edcraft_validator.domains.code.models import CodeTemplateAuthoringRequest

pytestmark = pytest.mark.openai_live


def test_real_openai_template_authoring() -> None:
    """Exercise the configured OpenAI model before submitting a PR."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    approved = TemplateApplication().author(
        CodeTemplateAuthoringRequest(topic="arithmetic", difficulty="beginner"),
        domain="code",
        provider="openai",
    )

    assert approved.validation.cases_validated >= 4
    assert len(approved.template.distractors) == 3
    assert approved.template.topic == "arithmetic"
    assert approved.template.difficulty == "beginner"
    assert approved.authoring is not None
    assert approved.authoring.provider == "openai"
    assert approved.authoring.model
