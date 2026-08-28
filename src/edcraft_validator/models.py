from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GeneratedQuestion(BaseModel):
    """Strict contract expected from an AI question generator."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, Any]
    question: str = Field(min_length=1)
    proposed_answer: Any
    distractors: list[Any] = Field(min_length=2)
    distractor_reasons: list[str] = Field(default_factory=list)
    question_type: Literal["mcq"] = "mcq"

    @field_validator("code", mode="before", json_schema_input_type=str | list[str])
    @classmethod
    def join_code_lines(cls, value: Any) -> Any:
        """Normalize readable JSON line arrays to executable Python source."""
        if isinstance(value, list) and all(isinstance(line, str) for line in value):
            return "\n".join(value)
        return value

    @field_validator("code", "question")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    field: str | None = None


class TraceSummary(BaseModel):
    entry_function: str
    function_calls: int
    loop_executions: int
    branch_executions: int
    variable_snapshots: int


class ValidationReport(BaseModel):
    status: Literal["valid", "invalid", "execution_error"]
    actual_answer: Any | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    trace_summary: TraceSummary | None = None

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"
