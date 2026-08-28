import math

from edcraft_validator.comparison import equivalent, same_value_shape
from edcraft_validator.executor import DockerExecutor, ExecutionBackend
from edcraft_validator.models import (
    GeneratedQuestion,
    TraceSummary,
    ValidationIssue,
    ValidationReport,
)
from edcraft_validator.safety import check_code_safety


class QuestionValidator:
    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        executor: ExecutionBackend | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        self.timeout_seconds = timeout_seconds
        self.executor = executor or DockerExecutor()

    def compute_answer(self, question: GeneratedQuestion) -> ValidationReport:
        safety = check_code_safety(question.code, question.entry_function)
        if not safety.is_safe:
            return ValidationReport(
                status="invalid",
                issues=[
                    ValidationIssue(code="UNSAFE_CODE", message=message, field="code")
                    for message in safety.errors
                ],
            )

        execution = self.executor.execute(
            question.code,
            question.entry_function,
            question.inputs,
            timeout_seconds=self.timeout_seconds,
        )
        if not execution.ok:
            return ValidationReport(
                status="execution_error",
                issues=[
                    ValidationIssue(
                        code=execution.error_code or "EXECUTION_FAILED",
                        message=execution.error_message or "Execution failed",
                        field="code",
                    )
                ],
            )

        return ValidationReport(
            status="valid",
            actual_answer=execution.answer,
            trace_summary=(
                TraceSummary.model_validate(execution.trace_summary)
                if execution.trace_summary
                else None
            ),
        )

    def validate(
        self,
        question: GeneratedQuestion,
        *,
        actual_answer: object | None = None,
        trace_summary: TraceSummary | None = None,
    ) -> ValidationReport:
        answer_was_supplied = actual_answer is not None
        if actual_answer is None:
            execution_report = self.compute_answer(question)
            if execution_report.status != "valid":
                return execution_report
            actual_answer = execution_report.actual_answer
            trace_summary = execution_report.trace_summary

        issues: list[ValidationIssue] = []
        if not answer_was_supplied and not equivalent(
            question.proposed_answer, actual_answer
        ):
            issues.append(
                ValidationIssue(
                    code="WRONG_PROPOSED_ANSWER",
                    message=(
                        "The proposed answer does not match the traced return value"
                    ),
                    field="proposed_answer",
                )
            )

        for index, distractor in enumerate(question.distractors):
            if not same_value_shape(distractor, actual_answer):
                issues.append(
                    ValidationIssue(
                        code="DISTRACTOR_TYPE_MISMATCH",
                        message="Distractor has a different value type from the answer",
                        field=f"distractors.{index}",
                    )
                )
            elif equivalent(distractor, actual_answer):
                issues.append(
                    ValidationIssue(
                        code="DISTRACTOR_EQUALS_ANSWER",
                        message=f"Distractor {index} is also correct",
                        field=f"distractors.{index}",
                    )
                )
            for previous_index, previous in enumerate(question.distractors[:index]):
                if equivalent(distractor, previous):
                    issues.append(
                        ValidationIssue(
                            code="DUPLICATE_DISTRACTOR",
                            message=(
                                f"Distractor {index} duplicates distractor "
                                f"{previous_index}"
                            ),
                            field=f"distractors.{index}",
                        )
                    )
                    break

        if question.entry_function not in question.question:
            issues.append(
                ValidationIssue(
                    code="QUESTION_MAY_NOT_IDENTIFY_FUNCTION",
                    message="Question text does not name the entry function",
                    severity="warning",
                    field="question",
                )
            )

        has_errors = any(issue.severity == "error" for issue in issues)
        return ValidationReport(
            status="invalid" if has_errors else "valid",
            actual_answer=actual_answer,
            issues=issues,
            trace_summary=trace_summary,
        )
