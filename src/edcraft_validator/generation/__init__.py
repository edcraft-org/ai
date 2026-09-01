"""Question-generation interfaces and orchestration."""

from importlib import import_module

from edcraft_validator.generation.base import (
    GenerationError,
    QuestionGenerator,
    QuestionTemplateGenerator,
)
from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.models import (
    GenerationAttempt,
    GenerationOutcome,
    GenerationRequest,
)

_LAZY_EXPORTS = {
    "FakeQuestionGenerator": (
        "edcraft_validator.generation.fake",
        "FakeQuestionGenerator",
    ),
    "GenerationService": ("edcraft_validator.generation.service", "GenerationService"),
    "OllamaQuestionGenerator": (
        "edcraft_validator.generation.ollama",
        "OllamaQuestionGenerator",
    ),
    "OpenAICompatibleQuestionGenerator": (
        "edcraft_validator.generation.openai",
        "OpenAICompatibleQuestionGenerator",
    ),
    "OpenAIQuestionGenerator": (
        "edcraft_validator.generation.openai",
        "OpenAIQuestionGenerator",
    ),
    "SocLaasQuestionGenerator": (
        "edcraft_validator.generation.openai",
        "SocLaasQuestionGenerator",
    ),
    "available_providers": (
        "edcraft_validator.generation.registry",
        "available_providers",
    ),
    "available_template_providers": (
        "edcraft_validator.generation.registry",
        "available_template_providers",
    ),
    "create_generator": ("edcraft_validator.generation.registry", "create_generator"),
    "create_template_generator": (
        "edcraft_validator.generation.registry",
        "create_template_generator",
    ),
    "register_provider": ("edcraft_validator.generation.registry", "register_provider"),
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
    "FakeQuestionGenerator",
    "GenerationAttempt",
    "GenerationOutcome",
    "GenerationRequest",
    "GenerationService",
    "GenerationError",
    "OpenAICompatibleQuestionGenerator",
    "OpenAIQuestionGenerator",
    "OllamaQuestionGenerator",
    "QuestionGenerator",
    "QuestionTemplateGenerator",
    "SocLaasQuestionGenerator",
    "available_providers",
    "available_template_providers",
    "create_generator",
    "create_template_generator",
    "register_provider",
]
