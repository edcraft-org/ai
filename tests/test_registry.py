import pytest

from edcraft_validator.domains.code.module import CodeDomain
from edcraft_validator.domains.registry import available_domains, create_domain
from edcraft_validator.generation.models import TemplateProviderSelection
from edcraft_validator.generation.registry import (
    available_model_providers,
    create_model_provider,
)


def test_registry_exposes_builtin_template_providers() -> None:
    assert available_model_providers()[:3] == ("openai", "ollama", "soclaas")
    selection = TemplateProviderSelection(provider="ollama")
    assert create_model_provider(selection).provider == "ollama"


def test_registry_passes_explicit_model_to_provider() -> None:
    selection = TemplateProviderSelection(provider="ollama", model="qwen-test")

    generator = create_model_provider(selection)

    assert generator.model == "qwen-test"


def test_registry_rejects_unknown_model_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_model_provider(TemplateProviderSelection(provider="missing"))


def test_domain_registry_exposes_code_without_changing_the_application() -> None:
    assert available_domains() == ("code",)
    assert isinstance(create_domain("code"), CodeDomain)


def test_domain_registry_rejects_unknown_domain() -> None:
    with pytest.raises(ValueError, match="Unsupported domain"):
        create_domain("math")
