"""Focused validation tools for the Python question domain."""

from __future__ import annotations

from edcraft_validator.comparison import equivalent, same_value_shape
from edcraft_validator.executor import ExecutionBackend
from edcraft_validator.models import ValidationIssue
from edcraft_validator.safety import check_code_safety
from edcraft_validator.validation.contracts import (
    ToolResult,
    ValidationContext,
)


class StaticSafetyTool:
    """Check generated Python before it crosses the execution boundary."""

    name = "static_safety"

    def validate(self, context: ValidationContext) -> ToolResult:
        candidate = context.candidate
        safety = check_code_safety(candidate.code, candidate.entry_function)
        if not safety.is_safe:
            return ToolResult(
                tool=self.name,
                status="failed",
                issues=[
                    ValidationIssue(code="UNSAFE_CODE", message=message, field="code")
                    for message in safety.errors
                ],
            )
        return ToolResult(tool=self.name, status="passed")


class PythonExecutionTool:
    """Compute the authoritative return value using the configured executor."""

    name = "python_execution"

    def __init__(self, executor: ExecutionBackend, timeout_seconds: float) -> None:
        self.executor = executor
        self.timeout_seconds = timeout_seconds

    def validate(self, context: ValidationContext) -> ToolResult:
        candidate = context.candidate
        execution = self.executor.execute(
            candidate.code,
            candidate.entry_function,
            candidate.inputs,
            timeout_seconds=self.timeout_seconds,
        )
        if not execution.ok:
            status = (
                "timeout" if execution.error_code == "EXECUTION_TIMEOUT" else "error"
            )
            return ToolResult(
                tool=self.name,
                status=status,
                issues=[
                    ValidationIssue(
                        code=execution.error_code or "EXECUTION_FAILED",
                        message=execution.error_message or "Execution failed",
                        field="code",
                    )
                ],
            )
        return ToolResult(
            tool=self.name,
            status="passed",
            facts={
                "actual_answer": execution.answer,
                "trace_summary": execution.trace_summary,
            },
        )


class DistractorConsistencyTool:
    """Check that MCQ alternatives are wrong, unique, and type-compatible."""

    name = "distractor_consistency"

    def validate(self, context: ValidationContext) -> ToolResult:
        actual_answer = context.actual_answer
        if not context.answer_available:
            return ToolResult(
                tool=self.name,
                status="skipped",
                issues=[
                    ValidationIssue(
                        code="MISSING_ACTUAL_ANSWER",
                        message="Distractors require an authoritative answer",
                    )
                ],
            )
        issues: list[ValidationIssue] = []
        candidate = context.candidate
        if (
            context.expected_distractors is not None
            and len(candidate.distractors) != context.expected_distractors
        ):
            issues.append(
                ValidationIssue(
                    code="DISTRACTOR_COUNT_MISMATCH",
                    message=(
                        f"Expected {context.expected_distractors} items, received "
                        f"{len(candidate.distractors)}"
                    ),
                    field="distractors",
                )
            )
        if candidate.distractor_reasons and len(candidate.distractor_reasons) != len(
            candidate.distractors
        ):
            issues.append(
                ValidationIssue(
                    code="DISTRACTOR_REASON_COUNT_MISMATCH",
                    message=(
                        f"Expected {len(candidate.distractors)} reasons, received "
                        f"{len(candidate.distractor_reasons)}"
                    ),
                    field="distractor_reasons",
                )
            )
        for index, distractor in enumerate(candidate.distractors):
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
            for previous_index, previous in enumerate(candidate.distractors[:index]):
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

        if candidate.proposed_answer is not None and not equivalent(
            candidate.proposed_answer, actual_answer
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
        return ToolResult(
            tool=self.name,
            status="failed" if issues else "passed",
            issues=issues,
        )


class QuestionWordingTool:
    """Provide advisory checks for the natural-language question."""

    name = "question_wording"

    def validate(self, context: ValidationContext) -> ToolResult:
        candidate = context.candidate
        issues: list[ValidationIssue] = []
        if candidate.entry_function not in candidate.question:
            issues.append(
                ValidationIssue(
                    code="QUESTION_MAY_NOT_IDENTIFY_FUNCTION",
                    message="Question text does not name the entry function",
                    severity="warning",
                    field="question",
                )
            )
        return ToolResult(
            tool=self.name,
            status="passed",
            issues=issues,
        )
