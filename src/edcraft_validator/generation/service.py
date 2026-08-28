import time
import uuid
from pathlib import Path

from edcraft_validator.generation.base import (
    QuestionGenerator,
    QuestionValidationBackend,
)
from edcraft_validator.generation.logging import JsonlAttemptLogger
from edcraft_validator.generation.models import (
    GenerationAttempt,
    GenerationOutcome,
    GenerationRequest,
    QuestionDraft,
)
from edcraft_validator.models import (
    GeneratedQuestion,
    ValidationIssue,
    ValidationReport,
)

DEFAULT_ATTEMPT_LOG = Path(".artifacts/generation_attempts.jsonl")


class GenerationService:
    """Generate candidates until one is valid or the attempt limit is reached."""

    def __init__(
        self,
        generator: QuestionGenerator,
        validator: QuestionValidationBackend,
        *,
        max_attempts: int = 3,
        max_distractor_attempts: int = 3,
        attempt_log_path: Path | None = DEFAULT_ATTEMPT_LOG,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be greater than zero")
        if max_distractor_attempts < 1:
            raise ValueError("max_distractor_attempts must be greater than zero")
        self.generator = generator
        self.validator = validator
        self.max_attempts = max_attempts
        self.max_distractor_attempts = max_distractor_attempts
        self.logger = (
            JsonlAttemptLogger(attempt_log_path)
            if attempt_log_path is not None
            else None
        )

    def generate(self, request: GenerationRequest) -> GenerationOutcome:
        run_id = uuid.uuid4().hex
        attempts: list[GenerationAttempt] = []
        feedback = None

        for attempt_number in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            if hasattr(self.generator, "generate_draft") and hasattr(
                self.validator, "compute_answer"
            ):
                question, report = self._generate_two_stage(
                    request, feedback
                )
            else:
                question = self.generator.generate(request, feedback=feedback)
                report = self._validate_candidate(request, question)
            attempt = GenerationAttempt(
                attempt_number=attempt_number,
                question=question,
                validation_report=report,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            attempts.append(attempt)
            if self.logger is not None:
                self.logger.log(run_id, request, attempt)

            if report.status == "valid":
                return GenerationOutcome(
                    run_id=run_id,
                    status="accepted",
                    request=request,
                    question=question,
                    attempts=attempts,
                )
            if report.status == "execution_error":
                return GenerationOutcome(
                    run_id=run_id,
                    status="execution_error",
                    request=request,
                    attempts=attempts,
                )
            feedback = report

        return GenerationOutcome(
            run_id=run_id,
            status="rejected",
            request=request,
            attempts=attempts,
        )

    def _generate_two_stage(
        self,
        request: GenerationRequest,
        feedback: ValidationReport | None,
    ) -> tuple[GeneratedQuestion, ValidationReport]:
        draft: QuestionDraft = self.generator.generate_draft(
            request, feedback=feedback
        )
        placeholder = GeneratedQuestion.model_validate(
            {
                **draft.model_dump(),
                "proposed_answer": None,
                "distractors": [None] * request.num_distractors,
            }
        )
        answer_report = self.validator.compute_answer(placeholder)
        if answer_report.status != "valid":
            return placeholder, answer_report

        question = GeneratedQuestion.model_validate(
            {
                **draft.model_dump(),
                "proposed_answer": answer_report.actual_answer,
                "distractors": draft.distractors[: request.num_distractors],
            }
        )
        report = self.validator.validate(
            question,
            actual_answer=answer_report.actual_answer,
            trace_summary=answer_report.trace_summary,
        )
        return question, report

    def _validate_candidate(
        self,
        request: GenerationRequest,
        question: GeneratedQuestion,
    ) -> ValidationReport:
        if len(question.distractors) != request.num_distractors:
            return ValidationReport(
                status="invalid",
                issues=[
                    ValidationIssue(
                        code="DISTRACTOR_COUNT_MISMATCH",
                        message=(
                            f"Expected {request.num_distractors} distractors, "
                            f"received {len(question.distractors)}"
                        ),
                        field="distractors",
                    )
                ],
            )
        return self.validator.validate(question)
