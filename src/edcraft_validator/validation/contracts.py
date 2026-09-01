"""Contracts shared by domain-specific validation pipelines."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from edcraft_validator.models import (
    QuestionCandidate,
    TraceSummary,
    ValidationIssue,
    ValidationReport,
)

ToolStatus = Literal["passed", "failed", "error", "timeout", "skipped"]
ValidationDecision = Literal[
    "accepted",
    "rejected",
    "execution_error",
    "indeterminate",
]


class ValidationContext(BaseModel):
    """Facts accumulated as tools in a validation pipeline run."""

    candidate: QuestionCandidate
    expected_distractors: int | None = None
    actual_answer: Any | None = None
    answer_available: bool = False
    trace_summary: TraceSummary | None = None
    facts: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The isolated result of one validation tool."""

    tool: str
    status: ToolStatus
    issues: list[ValidationIssue] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(default=0, ge=0)


class ValidationRun(BaseModel):
    """Evidence and decision produced by a validation pipeline."""

    decision: ValidationDecision
    results: list[ToolResult] = Field(default_factory=list)
    actual_answer: Any | None = None
    trace_summary: TraceSummary | None = None

    @property
    def issues(self) -> list[ValidationIssue]:
        return [issue for result in self.results for issue in result.issues]

    def to_report(self) -> ValidationReport:
        """Expose the legacy report shape at the application boundary."""
        status = {
            "accepted": "valid",
            "rejected": "invalid",
            "indeterminate": "invalid",
            "execution_error": "execution_error",
        }[self.decision]
        return ValidationReport(
            status=status,
            actual_answer=self.actual_answer,
            issues=self.issues,
            trace_summary=self.trace_summary,
            tool_results=[result.model_dump(mode="json") for result in self.results],
        )
