from typing import Protocol

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import GeneratedQuestion, TraceSummary, ValidationReport


class GenerationError(RuntimeError):
    """Raised when a provider cannot produce a usable draft."""


class QuestionGenerator(Protocol):
    """Model-independent contract for producing a question in two stages."""

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft: ...


class QuestionValidationBackend(Protocol):
    def compute_answer(self, question: GeneratedQuestion) -> ValidationReport: ...

    def validate(
        self,
        question: GeneratedQuestion,
        *,
        actual_answer: object | None = None,
        trace_summary: TraceSummary | None = None,
    ) -> ValidationReport: ...
