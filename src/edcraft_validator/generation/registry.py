"""Template-provider registry used by the CLI and application layer."""

from collections.abc import Callable

from edcraft_validator.generation.base import QuestionTemplateGenerator
from edcraft_validator.generation.ollama import OllamaTemplateGenerator
from edcraft_validator.generation.openai import (
    OpenAITemplateGenerator,
    SocLaasTemplateGenerator,
)

TemplateProviderFactory = Callable[[], QuestionTemplateGenerator]

_TEMPLATE_PROVIDER_FACTORIES: dict[str, TemplateProviderFactory] = {
    "openai": OpenAITemplateGenerator,
    "ollama": OllamaTemplateGenerator,
    "soclaas": SocLaasTemplateGenerator,
}


def register_template_provider(name: str, factory: TemplateProviderFactory) -> None:
    """Register a template provider without changing CLI routing code."""
    if not name or not name.strip():
        raise ValueError("provider name must not be blank")
    if name in _TEMPLATE_PROVIDER_FACTORIES:
        raise ValueError(f"provider is already registered: {name}")
    _TEMPLATE_PROVIDER_FACTORIES[name] = factory


def available_template_providers() -> tuple[str, ...]:
    """Return AI providers that can author reusable templates."""
    return tuple(_TEMPLATE_PROVIDER_FACTORIES)


def create_template_generator(provider: str) -> QuestionTemplateGenerator:
    """Construct a template author without exposing provider-specific classes."""
    try:
        factory = _TEMPLATE_PROVIDER_FACTORIES[provider]
    except KeyError as exc:
        supported = ", ".join(available_template_providers())
        raise ValueError(
            f"Unsupported template provider {provider!r}; choose one of: {supported}"
        ) from exc
    return factory()
