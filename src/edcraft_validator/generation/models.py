from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.models import (
    GeneratedQuestion,
    QuestionCandidate,
    ValidationReport,
)

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


# Backwards-compatible name for callers of the generation package.  The
# provider boundary produces the domain-level candidate contract.
QuestionDraft = QuestionCandidate


class GenerationAttempt(BaseModel):
    attempt_number: int = Field(ge=1)
    question: GeneratedQuestion | None = None
    distractor_reasons: list[str] = Field(default_factory=list)
    validation_report: ValidationReport
    duration_ms: float = Field(ge=0)


class GenerationOutcome(BaseModel):
    run_id: str
    status: Literal["accepted", "rejected", "execution_error"]
    request: GenerationRequest
    question: GeneratedQuestion | None = None
    attempts: list[GenerationAttempt]
