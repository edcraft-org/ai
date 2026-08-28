from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.models import GeneratedQuestion, ValidationReport

ProgrammingTopic = Literal[
    "arithmetic",
    "conditionals",
    "loops",
    "functions",
    "lists",
]
Difficulty = Literal["beginner", "intermediate", "advanced"]


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    topic: ProgrammingTopic
    difficulty: Difficulty
    num_distractors: int = Field(default=3, ge=2, le=3)


class QuestionDraft(BaseModel):
    """Model-generated question data before deterministic answer computation."""

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, object]
    question: str = Field(min_length=1)
    distractors: list[object] = Field(min_length=2)
    distractor_reasons: list[str] = Field(default_factory=list)
    question_type: Literal["mcq"] = "mcq"


class GenerationAttempt(BaseModel):
    attempt_number: int = Field(ge=1)
    question: GeneratedQuestion
    distractor_reasons: list[str] = Field(default_factory=list)
    validation_report: ValidationReport
    duration_ms: float = Field(ge=0)


class GenerationOutcome(BaseModel):
    run_id: str
    status: Literal["accepted", "rejected", "execution_error"]
    request: GenerationRequest
    question: GeneratedQuestion | None = None
    attempts: list[GenerationAttempt]
