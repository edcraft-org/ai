import pytest
from live_provider_helpers import check_live_workflow

from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider

pytestmark = pytest.mark.ollama_live


def test_real_ollama_template_workflow() -> None:
    """Exercise the configured local model using the same workflow as OpenAI."""
    provider = create_model_provider(TemplateProviderSelection(provider="ollama"))
    check_live_workflow(provider, reviewed_inputs=True)
