import math

from edcraft_validator.domains.code.pipeline import PythonValidationPipeline
from edcraft_validator.executor import ExecutionBackend
from edcraft_validator.models import (
    GeneratedQuestion,
    QuestionCandidate,
    TraceSummary,
    ValidationReport,
)
from edcraft_validator.validation.contracts import ValidationContext, ValidationRun

_UNSET = object()


class QuestionValidator:
    """Validate code questions through the current Python domain pipeline.

    This small facade preserves the original public API.  The implementation
    lives in focused tools so future domains can provide different pipelines.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        executor: ExecutionBackend | None = None,
        pipeline: PythonValidationPipeline | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        if pipeline is not None and executor is not None:
            raise ValueError("provide either pipeline or executor, not both")
        self.timeout_seconds = timeout_seconds
        self.pipeline = pipeline or PythonValidationPipeline(
            timeout_seconds=timeout_seconds,
            executor=executor,
        )

    def compute_answer(self, question: GeneratedQuestion) -> ValidationReport:
        return self.compute_answer_run(question).to_report()

    def compute_answer_run(self, question: GeneratedQuestion) -> ValidationRun:
        """Return detailed tool evidence for answer computation."""
        context = ValidationContext(
            candidate=question_to_candidate(question),
        )
        return self.pipeline.compute_answer(context)

    def validate(
        self,
        question: GeneratedQuestion,
        *,
        actual_answer: object = _UNSET,
        trace_summary: TraceSummary | None = None,
    ) -> ValidationReport:
        return self.validate_run(
            question,
            actual_answer=actual_answer,
            trace_summary=trace_summary,
        ).to_report()

    def validate_run(
        self,
        question: GeneratedQuestion,
        *,
        actual_answer: object = _UNSET,
        trace_summary: TraceSummary | None = None,
    ) -> ValidationRun:
        """Return detailed tool evidence for a complete validation run."""
        context = ValidationContext(
            candidate=question_to_candidate(question),
            actual_answer=None if actual_answer is _UNSET else actual_answer,
            answer_available=actual_answer is not _UNSET,
            trace_summary=trace_summary,
        )
        return self.pipeline.validate(context)


def question_to_candidate(question: GeneratedQuestion) -> QuestionCandidate:
    """Convert the public question shape to the untrusted pipeline shape."""
    return QuestionCandidate.from_question(question)
