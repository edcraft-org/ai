"""Canonical request, proposal, template, and question schemas for math."""

from __future__ import annotations

from string import Formatter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.math.math_types import (
    DEFAULT_DISTRACTORS,
    MATH_ADVISORY_CHECK_NAMES,
    MATH_CHECKING_MODE,
    MATH_FORMAT_VERSION,
    MATH_PARAMETER_NAMES,
    MATH_VALIDATOR_VERSION,
    MAX_DISTRACTOR_CANDIDATES,
    MAX_DISTRACTORS,
    MAX_EQUATION_TEMPLATE_LENGTH,
    MAX_EXPRESSION_LENGTH,
    MAX_PARAMETER_VALUE,
    MAX_PARAMETER_VALUES,
    MAX_PROMPT_LENGTH,
    MAX_QUESTION_TEMPLATE_LENGTH,
    MAX_REASON_TEMPLATE_LENGTH,
    MIN_DISTRACTORS,
    MIN_PARAMETER_VALUE,
    MIN_PARAMETER_VALUES,
    Difficulty,
)
from edcraft_validator.validation.validation_contracts import ValidationEvidence

_QUESTION_FIELDS = frozenset({*MATH_PARAMETER_NAMES, "equation"})


class MathTemplateRequest(BaseModel):
    """Free-form authoring request for one reusable linear-equation template."""

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


class MathParameter(BaseModel):
    """A bounded set of integer values for one equation coefficient."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    values: list[int] = Field(
        min_length=MIN_PARAMETER_VALUES, max_length=MAX_PARAMETER_VALUES
    )

    @model_validator(mode="after")
    def validate_values(self) -> MathParameter:
        if len(self.values) != len(set(self.values)):
            raise ValueError("parameter values must be unique")
        if any(
            value < MIN_PARAMETER_VALUE or value > MAX_PARAMETER_VALUE
            for value in self.values
        ):
            raise ValueError(
                "parameter values must be integers from "
                f"{MIN_PARAMETER_VALUE} to {MAX_PARAMETER_VALUE}"
            )
        return self


class MathDistractorRecipe(BaseModel):
    """A deterministic misconception applied to concrete parameter values."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(
        min_length=1,
        max_length=MAX_EXPRESSION_LENGTH,
        description="Arithmetic expression using a, b, c, or x.",
    )
    reason_template: str = Field(min_length=1, max_length=MAX_REASON_TEMPLATE_LENGTH)

    @field_validator("expression", "reason_template")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class MathTemplateContent(BaseModel):
    """Model-authored fields that require generative judgment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    equation_template: str = Field(
        min_length=1, max_length=MAX_EQUATION_TEMPLATE_LENGTH
    )
    question_template: str = Field(
        min_length=1, max_length=MAX_QUESTION_TEMPLATE_LENGTH
    )
    parameters: list[MathParameter] = Field(min_length=3, max_length=3)
    answer_expression: str = Field(min_length=1, max_length=MAX_EXPRESSION_LENGTH)
    distractors: list[MathDistractorRecipe] = Field(
        min_length=MIN_DISTRACTORS, max_length=MAX_DISTRACTOR_CANDIDATES
    )

    @field_validator("equation_template", "question_template", "answer_expression")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_and_template_domain(self) -> MathTemplateContent:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)) or set(names) != set(MATH_PARAMETER_NAMES):
            raise ValueError("parameters must be exactly a, b, and c")
        coefficient_a = next(
            parameter for parameter in self.parameters if parameter.name == "a"
        )
        if 0 in coefficient_a.values:
            raise ValueError("parameter a must never be zero")
        validate_equation_template(self.equation_template)
        validate_question_template(self.question_template)
        return self


class MathTemplateCandidate(MathTemplateContent):
    """Provider-neutral reusable template contract for linear equations."""

    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    difficulty: Difficulty
    question_type: Literal["mcq"] = "mcq"


class MathValidationSummary(BaseModel):
    """Complete-domain evidence without per-question answer tables."""

    model_config = ConfigDict(extra="forbid", strict=True)

    validator_version: Literal["mcp-math-template-v1"] = MATH_VALIDATOR_VERSION
    checking_mode: Literal["exhaustive_domain"] = MATH_CHECKING_MODE
    combinations_checked: int = Field(ge=1)
    max_combinations: int = Field(ge=1)
    seed: int = 0
    evidence: list[ValidationEvidence] = Field(min_length=1)

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
            raise ValueError("checked combinations exceed the bounded domain")
        return self


class ValidatedMathTemplate(ValidatedTemplateArtifact):
    """A template whose recipes passed exhaustive bounded checks."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format_version: Literal["1.0.0"] = MATH_FORMAT_VERSION
    template: MathTemplateCandidate
    validation: MathValidationSummary


class MathQuestionInstance(BaseModel):
    """A reproducible equation question expanded from a validated template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str
    artifact_id: str | None = None
    seed: int
    parameters: dict[str, int]
    equation: str = Field(min_length=1)
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)
    answer: str = Field(min_length=1)
    requires_manual_review: Literal[True] = True

    @model_validator(mode="after")
    def validate_choices(self) -> MathQuestionInstance:
        if self.correct_index >= len(self.choices):
            raise ValueError("correct_index must identify one choice")
        if len(self.choices) != len(set(self.choices)):
            raise ValueError("choices must be distinct")
        if self.choices[self.correct_index] != self.answer:
            raise ValueError("answer must equal the choice at correct_index")
        if set(self.parameters) != set(MATH_PARAMETER_NAMES):
            raise ValueError("question parameters must be exactly a, b, and c")
        return self


def template_fields(source: str) -> set[str]:
    """Return allowed placeholder fields, rejecting format specifications."""
    try:
        parsed = list(Formatter().parse(source))
    except ValueError as exc:
        raise ValueError(f"invalid text template: {exc}") from exc
    fields: set[str] = set()
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if not field_name:
            raise ValueError("text templates require named placeholders")
        if format_spec or conversion:
            raise ValueError(
                "text templates do not support conversions or format specifications"
            )
        fields.add(field_name)
    return fields


def validate_equation_template(source: str) -> None:
    """Require exactly the a, b, and c placeholders in the equation."""
    if template_fields(source) != set(MATH_PARAMETER_NAMES):
        raise ValueError(
            "equation_template must contain {a}, {b}, and {c} placeholders"
        )


def validate_question_template(source: str) -> None:
    """Allow only parameter names and the rendered equation in question text."""
    unknown = template_fields(source) - _QUESTION_FIELDS
    if unknown:
        raise ValueError(
            "question_template uses unsupported placeholders: "
            + ", ".join(sorted(unknown))
        )


def render_math_text(source: str, values: dict[str, object]) -> str:
    """Render a template after checking that every placeholder has a value."""
    fields = template_fields(source)
    missing = fields - set(values)
    if missing:
        raise ValueError(
            "text template uses unknown placeholders: " + ", ".join(sorted(missing))
        )
    rendered = source.format_map(values)
    if not rendered.strip():
        raise ValueError("rendered text must not be blank")
    return rendered
