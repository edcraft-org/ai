"""Provider-neutral interfaces for reusable question-template authoring."""

from edcraft_validator.generation.base import (
    GenerationError,
    ModelProvider,
    StructuredGenerationRequest,
)

__all__ = [
    "GenerationError",
    "ModelProvider",
    "StructuredGenerationRequest",
]
