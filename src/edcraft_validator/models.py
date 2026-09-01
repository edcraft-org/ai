from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionCandidate(BaseModel):
    """Provider-neutral, untrusted question candidate.

    A candidate becomes a :class:`GeneratedQuestion` only after a validation
    pipeline computes and supplies the authoritative answer.  Keeping that
    transition explicit prevents provider output from being mistaken for a
    trusted question.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, Any]
    question: str = Field(min_length=1)
    distractors: list[Any] = Field(min_length=2)
    distractor_reasons: list[str] = Field(default_factory=list)
    proposed_answer: Any | None = None
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

    @classmethod
    def from_question(cls, question: "GeneratedQuestion") -> "QuestionCandidate":
        """Create an untrusted candidate view of an existing question."""
        return cls(
            code=question.code,
            entry_function=question.entry_function,
            inputs=question.inputs,
            question=question.question,
            distractors=question.distractors,
            proposed_answer=question.proposed_answer,
            question_type=question.question_type,
        )

    def with_answer(self, answer: Any) -> "GeneratedQuestion":
        """Promote this candidate to the public validated-question model."""
        return GeneratedQuestion(
            code=self.code,
            entry_function=self.entry_function,
            inputs=self.inputs,
            question=self.question,
            proposed_answer=answer,
            distractors=self.distractors,
            question_type=self.question_type,
        )


class GeneratedQuestion(BaseModel):
    """Strict contract for a question after answer validation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, Any]
    question: str = Field(min_length=1)
    proposed_answer: Any
    distractors: list[Any] = Field(min_length=2)
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
    tool_results: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"
