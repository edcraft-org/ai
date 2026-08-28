"""Question-generation interfaces and orchestration."""

from edcraft_validator.generation.base import QuestionGenerator
from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.models import (
    GenerationAttempt,
    GenerationOutcome,
    GenerationRequest,
)
from edcraft_validator.generation.ollama import OllamaQuestionGenerator
from edcraft_validator.generation.openai import OpenAICompatibleQuestionGenerator
from edcraft_validator.generation.service import GenerationService

__all__ = [
    "FakeQuestionGenerator",
    "GenerationAttempt",
    "GenerationOutcome",
    "GenerationRequest",
    "GenerationService",
    "OpenAICompatibleQuestionGenerator",
    "OllamaQuestionGenerator",
    "QuestionGenerator",
]
