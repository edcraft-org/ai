"""Canonical request, proposal, template, and question schemas for math."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.domain_support import TemplateRequest
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from edcraft_validator.domains.math.math_types import (
    MATH_CHECKING_MODE,
    MATH_FORMAT_VERSION,
    MATH_VALIDATOR_VERSION,
    Difficulty,
)
from edcraft_validator.validation.property_summary import PropertyCheckSummary
from edcraft_validator.validation.validation_contracts import ValidationEvidence

# Retired linear-equation authoring fields. A proposal that still carries any
# of them is rejected instead of silently ignored.
_LEGACY_AUTHORING_FIELDS = (
    "equation_template",
    "question_template",
    "parameters",
    "answer_expression",
    "distractors",
)


# One request shape serves every domain; the name is kept for existing imports.
MathTemplateRequest = TemplateRequest


class MathTemplateContent(BaseModel):
    """Model-authored generic template: one typed IR item family.

    The proposal authors any closed-vocabulary goal (solve, derivative,
    determinant, and so on) expanded over a finite parameter grid. The retired
    linear-equation authoring fields are rejected.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathTemplateSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_authoring_mode(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        legacy = [field for field in _LEGACY_AUTHORING_FIELDS if field in value]
        if legacy:
            raise ValueError(
                "legacy linear authoring fields are removed; return a generic "
                f"item instead (unexpected fields: {', '.join(legacy)})"
            )
        return value

    @model_validator(mode="after")
    def require_item(self) -> MathTemplateContent:
        if self.item is None:
            raise ValueError(
                "item is required; author a generic math template item family"
            )
        return self


class MathTemplateCandidate(MathTemplateContent):
    """Provider-neutral reusable template contract for math items."""

    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    difficulty: Difficulty
    question_type: Literal["mcq"] = "mcq"


class MathValidationSummary(PropertyCheckSummary):
    """Sampled-domain evidence without per-question answer tables."""

    validator_version: Literal["mcp-math-template-v1"] = MATH_VALIDATOR_VERSION
    checking_mode: Literal["property_based"] = MATH_CHECKING_MODE
    evidence: list[ValidationEvidence] = Field(min_length=1)


class ValidatedMathTemplate(ValidatedTemplateArtifact):
    """A template whose recipes passed bounded property-based checks."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format_version: Literal["1.0.0"] = MATH_FORMAT_VERSION
    template: MathTemplateCandidate
    validation: MathValidationSummary


class QuestionSegment(BaseModel):
    """One piece of a question prompt: prose or LaTeX."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["text", "math"]
    value: str = Field(min_length=1)


class MathQuestionInstance(BaseModel):
    """A reproducible question expanded from a validated template.

    Generic IR templates carry their declared parameter values as exact
    strings and set ``topic``; ``equation`` is the rendered mathematical
    object. The optional LaTeX fields carry the same maths typeset for KaTeX.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str
    artifact_id: str | None = None
    seed: int
    parameters: dict[str, int | str]
    equation: str = Field(min_length=1)
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)
    answer: str = Field(min_length=1)
    topic: str | None = None
    requires_manual_review: Literal[True] = True
    equation_latex: str | None = None
    choices_latex: list[str] | None = None
    answer_latex: str | None = None
    question_segments: list[QuestionSegment] | None = None

    @model_validator(mode="after")
    def validate_choices(self) -> MathQuestionInstance:
        if self.correct_index >= len(self.choices):
            raise ValueError("correct_index must identify one choice")
        if len(self.choices) != len(set(self.choices)):
            raise ValueError("choices must be distinct")
        if self.choices[self.correct_index] != self.answer:
            raise ValueError("answer must equal the choice at correct_index")

        return self
