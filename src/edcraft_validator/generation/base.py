from typing import Protocol

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import GeneratedQuestion, ValidationReport


class QuestionGenerator(Protocol):
    """Model-independent contract for producing a question in two stages."""

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft: ...

    # Kept as a compatibility method for existing integrations.
    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion: ...


class QuestionValidationBackend(Protocol):
    def validate(self, question: GeneratedQuestion) -> ValidationReport: ...
