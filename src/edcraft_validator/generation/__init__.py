"""AI provider interfaces for reusable question-template authoring."""

from importlib import import_module

from edcraft_validator.generation.base import GenerationError, QuestionTemplateGenerator
from edcraft_validator.generation.models import TemplateAuthoringRequest

_LAZY_EXPORTS = {
    "OllamaTemplateGenerator": (
        "edcraft_validator.generation.ollama",
        "OllamaTemplateGenerator",
    ),
    "OpenAICompatibleTemplateGenerator": (
        "edcraft_validator.generation.openai",
        "OpenAICompatibleTemplateGenerator",
    ),
    "OpenAITemplateGenerator": (
        "edcraft_validator.generation.openai",
        "OpenAITemplateGenerator",
    ),
    "SocLaasTemplateGenerator": (
        "edcraft_validator.generation.openai",
        "SocLaasTemplateGenerator",
    ),
    "available_template_providers": (
        "edcraft_validator.generation.registry",
        "available_template_providers",
    ),
    "create_template_generator": (
        "edcraft_validator.generation.registry",
        "create_template_generator",
    ),
    "register_template_provider": (
        "edcraft_validator.generation.registry",
        "register_template_provider",
    ),
}


def __getattr__(name: str):
    """Load provider modules only when a provider export is requested."""
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "GenerationError",
    "OllamaTemplateGenerator",
    "OpenAICompatibleTemplateGenerator",
    "OpenAITemplateGenerator",
    "QuestionTemplateGenerator",
    "SocLaasTemplateGenerator",
    "TemplateAuthoringRequest",
    "available_template_providers",
    "create_template_generator",
    "register_template_provider",
]
