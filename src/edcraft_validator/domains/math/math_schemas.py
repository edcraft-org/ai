"""Canonical request, proposal, template, and question schemas for math."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from edcraft_validator.domains.math.math_types import (
    DEFAULT_DISTRACTORS,
    LEGACY_MATH_RELEVANCE_TOOL,
    MATH_ADVISORY_CHECK_NAMES,
    MATH_CHECKING_MODE,
    MATH_FORMAT_VERSION,
    MATH_VALIDATOR_VERSION,
    MAX_DISTRACTORS,
    MAX_PROMPT_LENGTH,
    MIN_DISTRACTORS,
    Difficulty,
)
from edcraft_validator.validation.check_names import TEMPLATE_RELEVANCE_CHECK
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


class MathTemplateRequest(BaseModel):
    """Free-form authoring request for one reusable math template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    difficulty: Difficulty
    num_distractors: int = Field(
        default=DEFAULT_DISTRACTORS, ge=MIN_DISTRACTORS, le=MAX_DISTRACTORS
    )

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


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


class MathValidationSummary(BaseModel):
    """Sampled-domain evidence without per-question answer tables."""

    model_config = ConfigDict(extra="forbid", strict=True)

    validator_version: Literal["mcp-math-template-v1"] = MATH_VALIDATOR_VERSION
    checking_mode: Literal["property_based"] = MATH_CHECKING_MODE
    # Samples graded by the harness and the template's declared domain size.
    combinations_checked: int = Field(ge=1)
    max_combinations: int = Field(ge=1)
    seed: int = 0
    evidence: list[ValidationEvidence] = Field(min_length=1)

    @field_validator("evidence", mode="before")
    @classmethod
    def migrate_legacy_relevance(cls, value: object) -> object:
        """Rewrite the retired relevance check name while reading old artifacts."""
        if not isinstance(value, list):
            return value
        migrated: list[object] = []
        seen: set[str] = set()
        for item in value:
            if isinstance(item, BaseModel):
                data = item.model_dump()
            elif isinstance(item, dict):
                data = dict(item)
            else:
                migrated.append(item)
                continue
            legacy = data.get("check") == LEGACY_MATH_RELEVANCE_TOOL
            if legacy:
                data["check"] = TEMPLATE_RELEVANCE_CHECK
            check = data.get("check")
            if isinstance(check, str):
                # An artifact rewritten after the rename can carry both names.
                # Evidence checks are unique by contract, so read-compat keeps
                # the first row for each name instead of rejecting old files.
                if check in seen:
                    continue
                seen.add(check)
            migrated.append(data)
        return migrated

    @model_validator(mode="after")
    def require_successful_unique_evidence(self) -> MathValidationSummary:
        checks = [item.check for item in self.evidence]
        if len(checks) != len(set(checks)):
            raise ValueError("validation evidence checks must be unique")
        if any(
            item.status != "passed" and item.check not in MATH_ADVISORY_CHECK_NAMES
            for item in self.evidence
        ):
            raise ValueError("checked templates require passing validation evidence")
        if self.combinations_checked > self.max_combinations:
            raise ValueError("checked combinations exceed the declared domain")
        return self


class ValidatedMathTemplate(ValidatedTemplateArtifact):
    """A template whose recipes passed bounded property-based checks."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format_version: Literal["1.0.0"] = MATH_FORMAT_VERSION
    template: MathTemplateCandidate
    validation: MathValidationSummary


class MathQuestionInstance(BaseModel):
    """A reproducible question expanded from a validated template.

    Generic IR templates carry their declared parameter values as exact
    strings and set ``topic``; ``equation`` is the rendered mathematical
    object.
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

    @model_validator(mode="after")
    def validate_choices(self) -> MathQuestionInstance:
        if self.correct_index >= len(self.choices):
            raise ValueError("correct_index must identify one choice")
        if len(self.choices) != len(set(self.choices)):
            raise ValueError("choices must be distinct")
        if self.choices[self.correct_index] != self.answer:
            raise ValueError("answer must equal the choice at correct_index")
        return self
