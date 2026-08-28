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
        attempt_log_path: Path | None = DEFAULT_ATTEMPT_LOG,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be greater than zero")
        self.generator = generator
        self.validator = validator
        self.max_attempts = max_attempts
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
            question, report, distractor_reasons = self._generate_draft(
                request, feedback
            )
            attempt = GenerationAttempt(
                attempt_number=attempt_number,
                question=question,
                distractor_reasons=distractor_reasons,
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

    def _generate_draft(
        self,
        request: GenerationRequest,
        feedback: ValidationReport | None,
    ) -> tuple[GeneratedQuestion, ValidationReport, list[str]]:
        draft: QuestionDraft = self.generator.generate_draft(
            request, feedback=feedback
        )
        if len(draft.distractors) != request.num_distractors:
            return self._draft_for_report(draft), self._count_report(
                request.num_distractors,
                len(draft.distractors),
                field="distractors",
                code="DISTRACTOR_COUNT_MISMATCH",
            ), draft.distractor_reasons
        if len(draft.distractor_reasons) != len(draft.distractors):
            return self._draft_for_report(draft), self._count_report(
                len(draft.distractors),
                len(draft.distractor_reasons),
                field="distractor_reasons",
                code="DISTRACTOR_REASON_COUNT_MISMATCH",
            ), draft.distractor_reasons

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
