from typing import Protocol

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.models import GeneratedQuestion, ValidationReport


class QuestionGenerator(Protocol):
    """Model-independent contract for producing one candidate question."""

    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion: ...


class QuestionValidationBackend(Protocol):
    def validate(self, question: GeneratedQuestion) -> ValidationReport: ...
