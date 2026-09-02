import pytest

from edcraft_validator.generation.registry import (
    available_template_providers,
    create_template_generator,
    register_template_provider,
)


def test_registry_exposes_builtin_template_providers() -> None:
    assert available_template_providers()[:3] == ("openai", "ollama", "soclaas")
    assert create_template_generator("ollama").provider == "ollama"


def test_registry_supports_template_provider_extensions() -> None:
    class CustomTemplateGenerator:
        provider = "custom"

        def generate_proposal(self, request):
            raise NotImplementedError

    register_template_provider("custom", CustomTemplateGenerator)

    assert isinstance(create_template_generator("custom"), CustomTemplateGenerator)


def test_registry_rejects_unknown_template_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported template provider"):
        create_template_generator("missing")
