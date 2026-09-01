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
from edcraft_validator.generation.observability import (
    AttemptTelemetry,
    GenerationMetrics,
    provider_metadata,
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
        attempt_log_path: Path | None = DEFAULT_ATTEMPT_LOG,
        metrics: GenerationMetrics | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be greater than zero")
        self.generator = generator
        self.validator = validator
        self.max_attempts = max_attempts
        self.metrics = metrics or GenerationMetrics()
        self.provider, self.model = provider_metadata(generator)
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
            generation_started = time.perf_counter()
            draft = self.generator.generate_draft(request, feedback=feedback)
            generation_duration_ms = (time.perf_counter() - generation_started) * 1000
            validation_started = time.perf_counter()
            question, report, distractor_reasons = self._validate_draft(request, draft)
            validation_duration_ms = (time.perf_counter() - validation_started) * 1000
            telemetry = AttemptTelemetry(
                provider=self.provider,
                model=self.model,
                generation_duration_ms=generation_duration_ms,
                validation_duration_ms=validation_duration_ms,
                status=report.status,
                issue_codes=tuple(issue.code for issue in report.issues),
            )
            self.metrics.record_attempt(telemetry)
            attempt = GenerationAttempt(
                attempt_number=attempt_number,
                question=question,
                distractor_reasons=distractor_reasons,
                validation_report=report,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            attempts.append(attempt)
            if self.logger is not None:
                self.logger.log(run_id, request, attempt, telemetry)

            if report.status == "valid":
                self.metrics.record_outcome("accepted")
                return GenerationOutcome(
                    run_id=run_id,
                    status="accepted",
                    request=request,
                    question=question,
                    attempts=attempts,
                )
            if report.status == "execution_error":
                self.metrics.record_outcome("execution_error")
                return GenerationOutcome(
                    run_id=run_id,
                    status="execution_error",
                    request=request,
                    attempts=attempts,
                )
            feedback = report

        self.metrics.record_outcome("rejected")
        return GenerationOutcome(
            run_id=run_id,
            status="rejected",
            request=request,
            attempts=attempts,
        )

    def _validate_draft(
        self,
        request: GenerationRequest,
        draft: QuestionDraft,
    ) -> tuple[GeneratedQuestion, ValidationReport, list[str]]:
        if len(draft.distractors) != request.num_distractors:
            return (
                self._draft_for_report(draft),
                self._count_report(
                    request.num_distractors,
                    len(draft.distractors),
                    field="distractors",
                    code="DISTRACTOR_COUNT_MISMATCH",
                ),
                draft.distractor_reasons,
            )
        if len(draft.distractor_reasons) != len(draft.distractors):
            return (
                self._draft_for_report(draft),
                self._count_report(
                    len(draft.distractors),
                    len(draft.distractor_reasons),
                    field="distractor_reasons",
                    code="DISTRACTOR_REASON_COUNT_MISMATCH",
                ),
                draft.distractor_reasons,
            )

        placeholder = GeneratedQuestion.model_validate(
            {
                "code": draft.code,
                "entry_function": draft.entry_function,
                "inputs": draft.inputs,
                "question": draft.question,
                "proposed_answer": None,
                "distractors": [None] * request.num_distractors,
                "question_type": draft.question_type,
            }
        )
        answer_report = self.validator.compute_answer(placeholder)
        if answer_report.status != "valid":
            return placeholder, answer_report, draft.distractor_reasons

        question = GeneratedQuestion.model_validate(
            {
                "code": draft.code,
                "entry_function": draft.entry_function,
                "inputs": draft.inputs,
                "question": draft.question,
                "proposed_answer": answer_report.actual_answer,
                "distractors": draft.distractors,
                "question_type": draft.question_type,
            }
        )
        report = self.validator.validate(
            question,
            actual_answer=answer_report.actual_answer,
            trace_summary=answer_report.trace_summary,
        )
        return question, report, draft.distractor_reasons

    @staticmethod
    def _draft_for_report(draft: QuestionDraft) -> GeneratedQuestion:
        return GeneratedQuestion.model_validate(
            {
                "code": draft.code,
                "entry_function": draft.entry_function,
                "inputs": draft.inputs,
                "question": draft.question,
                "proposed_answer": None,
                "distractors": draft.distractors,
                "question_type": draft.question_type,
            }
        )

    @staticmethod
    def _count_report(
        expected: int,
        received: int,
        answer_report: ValidationReport | None = None,
        *,
        field: str,
        code: str = "COUNT_MISMATCH",
    ) -> ValidationReport:
        return ValidationReport(
            status="invalid",
            actual_answer=answer_report.actual_answer if answer_report else None,
            issues=[
                ValidationIssue(
                    code=code,
                    message=f"Expected {expected} items, received {received}",
                    field=field,
                )
            ],
            trace_summary=answer_report.trace_summary if answer_report else None,
        )
