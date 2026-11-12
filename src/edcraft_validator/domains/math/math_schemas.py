"""Canonical request, proposal, template, and question schemas for math."""

from __future__ import annotations

from itertools import product
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
from edcraft_validator.text_templates import render_text_template, template_fields
from edcraft_validator.validation.check_names import TEMPLATE_RELEVANCE_CHECK
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


def parameter_combinations(
    parameters: list[MathParameter],
) -> list[dict[str, int]]:
    """Expand the declared finite parameter grid in stable order."""
    names = tuple(parameter.name for parameter in parameters)
    return [
        dict(zip(names, values, strict=True))
        for values in product(*(parameter.values for parameter in parameters))
    ]


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
    """Model-authored template: either a typed IR family or the legacy linear form.

    The generic ``item`` path authors any closed-vocabulary goal (solve,
    derivative, determinant, and so on). The legacy fields remain for the
    original linear-equation contract and its stored artifacts. Exactly one mode
    is present on every proposal.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathTemplateSpec | None = None
    equation_template: str | None = Field(
        default=None, min_length=1, max_length=MAX_EQUATION_TEMPLATE_LENGTH
    )
    question_template: str | None = Field(
        default=None, min_length=1, max_length=MAX_QUESTION_TEMPLATE_LENGTH
    )
    parameters: list[MathParameter] | None = Field(default=None)
    answer_expression: str | None = Field(
        default=None, min_length=1, max_length=MAX_EXPRESSION_LENGTH
    )
    distractors: list[MathDistractorRecipe] | None = Field(default=None)

    @field_validator("equation_template", "question_template", "answer_expression")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_authoring_mode(self) -> MathTemplateContent:
        legacy = [
            self.equation_template,
            self.question_template,
            self.parameters,
            self.answer_expression,
            self.distractors,
        ]
        if self.item is not None:
            if any(value is not None for value in legacy):
                raise ValueError(
                    "return either a generic item or the legacy linear fields, not both"
                )
            return self
        if any(value is None for value in legacy):
            raise ValueError(
                "the legacy authoring mode requires equation_template, "
                "question_template, parameters, answer_expression, and distractors; "
                "otherwise return a generic item"
            )
        equation_template = self.equation_template
        question_template = self.question_template
        parameters = self.parameters
        distractors = self.distractors
        if (
            equation_template is None
            or question_template is None
            or parameters is None
            or distractors is None
        ):
            raise ValueError("legacy authoring fields are required")
        if not MIN_DISTRACTORS <= len(distractors) <= MAX_DISTRACTOR_CANDIDATES:
            raise ValueError(
                f"distractors must contain {MIN_DISTRACTORS} to "
                f"{MAX_DISTRACTOR_CANDIDATES} recipes"
            )
        names = [parameter.name for parameter in parameters]
        if len(names) != len(set(names)) or set(names) != set(MATH_PARAMETER_NAMES):
            raise ValueError("parameters must be exactly a, b, and c")
        coefficient_a = next(
            parameter for parameter in parameters if parameter.name == "a"
        )
        if 0 in coefficient_a.values:
            raise ValueError("parameter a must never be zero")
        validate_equation_template(equation_template)
        validate_question_template(question_template)
        return self

    @property
    def uses_ir(self) -> bool:
        return self.item is not None


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
            raise ValueError("checked combinations exceed the bounded domain")
        return self


class ValidatedMathTemplate(ValidatedTemplateArtifact):
    """A template whose recipes passed exhaustive bounded checks."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format_version: Literal["1.0.0"] = MATH_FORMAT_VERSION
    template: MathTemplateCandidate
    validation: MathValidationSummary


class MathQuestionInstance(BaseModel):
    """A reproducible question expanded from a validated template.

    Legacy linear templates keep integer ``a``/``b``/``c`` parameters. Generic
    IR templates carry their declared parameter values as exact strings and set
    ``topic``; ``equation`` is the rendered mathematical object.
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
        if self.topic is None and set(self.parameters) != set(MATH_PARAMETER_NAMES):
            raise ValueError("question parameters must be exactly a, b, and c")
        return self


def validate_equation_template(source: str) -> None:
    """Require the canonical bounded linear form ``a*x + b = c``.

    The pilot supports exactly one equation shape. Fixing the layout lets the
    answer check solve the equation directly instead of trusting a model-written
    answer recipe, and it rejects powers, unknowns on both sides, and any other
    unsupported form before it can pass a technical check.
    """
    if template_fields(source) != set(MATH_PARAMETER_NAMES):
        raise ValueError(
            "equation_template must contain {a}, {b}, and {c} placeholders"
        )
    if "".join(source.split()) != "{a}x+{b}={c}":
        raise ValueError(
            "equation_template must use the supported {a}x + {b} = {c} form"
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
    return render_text_template(source, values)


def render_linear_equation(a: int, b: int, c: int) -> str:
    """Render the canonical ``a*x + b = c`` form the way a student reads it.

    Naive substitution turns a negative constant into ``+ -6`` and a unit
    coefficient into ``1x``. Neither changes the canonical solve, so this is a
    presentation rule only, applied to the one equation shape the domain
    supports.
    """
    if a == 1:
        coefficient = "x"
    elif a == -1:
        coefficient = "-x"
    else:
        coefficient = f"{a}x"
    if b > 0:
        constant = f" + {b}"
    elif b < 0:
        constant = f" - {abs(b)}"
    else:
        constant = ""
    return f"{coefficient}{constant} = {c}"
