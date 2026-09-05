"""Provider-neutral interfaces for reusable question-template authoring."""

from edcraft_validator.generation.base import (
    GenerationError,
    QuestionTemplateGenerator,
)
from edcraft_validator.generation.models import TemplateAuthoringRequest

__all__ = [
    "GenerationError",
    "QuestionTemplateGenerator",
    "TemplateAuthoringRequest",
]
