"""Question-generation interfaces and orchestration."""

from edcraft_validator.generation.base import GenerationError, QuestionGenerator
from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.models import (
    GenerationAttempt,
    GenerationOutcome,
    GenerationRequest,
)
from edcraft_validator.generation.ollama import OllamaQuestionGenerator
from edcraft_validator.generation.openai import (
    OpenAICompatibleQuestionGenerator,
    OpenAIQuestionGenerator,
    SocLaasQuestionGenerator,
)
from edcraft_validator.generation.registry import (
    available_providers,
    create_generator,
    register_provider,
)
from edcraft_validator.generation.service import GenerationService

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
    "SocLaasQuestionGenerator",
    "available_providers",
    "create_generator",
    "register_provider",
]
