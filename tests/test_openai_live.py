import os

import pytest

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider

pytestmark = pytest.mark.openai_live


def test_real_openai_template_authoring() -> None:
    """Exercise the configured OpenAI model before submitting a PR."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    provider = create_model_provider(TemplateProviderSelection(provider="openai"))
    validated = TemplateApplication().create_validated_template(
        CodeTemplateRequest(topic="arithmetic", difficulty="beginner"),
        domain=CodeDomain(),
        provider=provider,
    )

    assert validated.validation.cases_validated >= 4
    assert len(validated.template.distractors) == 3
    assert validated.template.topic == "arithmetic"
    assert validated.template.difficulty == "beginner"
    assert validated.authoring is not None
    assert validated.authoring.provider == "openai"
    assert validated.authoring.model
