"""Model-provider registry used by the CLI and evaluation entry points."""

from collections.abc import Callable

from edcraft_validator.llm.llm_contracts import ModelProvider, TemplateProviderSelection
from edcraft_validator.llm.ollama_provider import OllamaProvider
from edcraft_validator.llm.openai_compatible_provider import (
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
