"""Model-provider registry used by the CLI and application layer."""

from collections.abc import Callable

from edcraft_validator.generation.base import ModelProvider
from edcraft_validator.generation.models import TemplateProviderSelection
from edcraft_validator.generation.ollama import OllamaProvider
from edcraft_validator.generation.openai import (
    OpenAIProvider,
    SocLaasProvider,
)

ModelProviderFactory = Callable[[str | None], ModelProvider]

_MODEL_PROVIDER_FACTORIES: dict[str, ModelProviderFactory] = {
    "openai": lambda model: OpenAIProvider(model=model),
    "ollama": lambda model: OllamaProvider(model=model),
    "soclaas": lambda model: SocLaasProvider(model=model),
}


def available_model_providers() -> tuple[str, ...]:
    """Return providers that support structured generation."""
    return tuple(_MODEL_PROVIDER_FACTORIES)


def create_model_provider(
    selection: TemplateProviderSelection,
) -> ModelProvider:
    """Construct a provider without exposing its concrete adapter."""
    try:
        factory = _MODEL_PROVIDER_FACTORIES[selection.provider]
    except KeyError as exc:
        supported = ", ".join(available_model_providers())
        raise ValueError(
            f"Unsupported model provider {selection.provider!r}; choose one of: "
            f"{supported}"
        ) from exc
    return factory(selection.model)
