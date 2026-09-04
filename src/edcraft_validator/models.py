from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AnswerTarget = Literal[
    "return_value",
    "loop_iterations",
    "loop_executions",
    "branch_executions",
    "function_calls",
]


class GeneratedQuestion(BaseModel):
    """A deterministic question expanded from an approved template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, Any]
    question: str = Field(min_length=1)
    proposed_answer: Any
    distractors: list[Any] = Field(min_length=2)
    distractor_reasons: list[str] = Field(default_factory=list)
    answer_target: AnswerTarget = "return_value"
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
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    field: str | None = None
