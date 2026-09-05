"""Template-provider registry used by the CLI and application layer."""

from collections.abc import Callable

from edcraft_validator.generation.base import QuestionTemplateGenerator
from edcraft_validator.generation.models import TemplateProviderSelection
from edcraft_validator.generation.ollama import OllamaTemplateGenerator
from edcraft_validator.generation.openai import (
    OpenAITemplateGenerator,
    SocLaasTemplateGenerator,
)

TemplateProviderFactory = Callable[[str | None], QuestionTemplateGenerator]

_TEMPLATE_PROVIDER_FACTORIES: dict[str, TemplateProviderFactory] = {
    "openai": lambda model: OpenAITemplateGenerator(model=model),
    "ollama": lambda model: OllamaTemplateGenerator(model=model),
    "soclaas": lambda model: SocLaasTemplateGenerator(model=model),
}


def available_template_providers() -> tuple[str, ...]:
    """Return AI providers that can author reusable templates."""
    return tuple(_TEMPLATE_PROVIDER_FACTORIES)


def create_template_generator(
    selection: TemplateProviderSelection,
) -> QuestionTemplateGenerator:
    """Construct a template author without exposing provider-specific classes."""
    try:
        factory = _TEMPLATE_PROVIDER_FACTORIES[selection.provider]
    except KeyError as exc:
        supported = ", ".join(available_template_providers())
        raise ValueError(
            f"Unsupported template provider {selection.provider!r}; choose one of: "
            f"{supported}"
        ) from exc
    return factory(selection.model)
