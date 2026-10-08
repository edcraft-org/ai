import os

import pytest
from live_provider_helpers import check_live_workflow

from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider

pytestmark = pytest.mark.openai_live


def test_real_openai_template_authoring() -> None:
    """Exercise the configured OpenAI model before submitting a PR."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    provider = create_model_provider(TemplateProviderSelection(provider="openai"))
    check_live_workflow(provider)
