"""Closed wire and authoring models for the reusable-check pilot.

The wire models are the frozen cross-repository contract. Everything else in
this package is closed data: no model-authored Python reaches an interpreter.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CHECK_SCHEMA_VERSION: Literal["check-pilot/1"] = "check-pilot/1"
RECIPE_SCHEMA_VERSION: Literal["check-recipe/1"] = "check-recipe/1"
FAMILY_SCHEMA_VERSION: Literal["polynomial-family/1"] = "polynomial-family/1"
TEMPLATE_SCHEMA_VERSION: Literal["pilot-template/1"] = "pilot-template/1"
RECIPE_OPERATION_SET: Literal["polynomial-derivative/1"] = "polynomial-derivative/1"
RENDERER_VERSION: Literal["polynomial-mcq/1"] = "polynomial-mcq/1"
MAX_RECIPE_CASES = 600

QualificationStatus = Literal["passed", "failed", "inconclusive", "error"]
TemplateStatus = Literal["ready", "needs_review", "error"]
ApprovalStatus = Literal["unreviewed", "approved", "rejected"]


class PilotModel(BaseModel):
    """Strict, immutable model; unexpected fields are always rejected."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False
    )


class CheckRef(PilotModel):
    check_id: str = Field(pattern=r"^chk_[0-9a-f]{16,64}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Qualification(PilotModel):
    status: QualificationStatus
    checking_mode: Literal["property_based"] = "property_based"
    accepted_cases: int = Field(ge=0)
    execution_calls: int = Field(ge=0)
    seed: int = Field(ge=0)
    max_examples: int = Field(ge=1)
    max_execution_calls: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)
    counterexample: dict[str, Any] | None = None
    findings: list[str] = Field(default_factory=list)
    versions: dict[str, str] = Field(default_factory=dict)


class CheckRecord(PilotModel):
    check_ref: CheckRef
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    scope: dict[str, Any]
    definition: dict[str, Any]
    qualification: Qualification
    provenance: dict[str, Any]
    created_at: str = Field(min_length=1)


class PilotTemplateRecord(PilotModel):
    template_id: str = Field(pattern=r"^tpl_[0-9a-f]{16,64}$")
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt: str = Field(min_length=1, max_length=4000)
    status: TemplateStatus
    approval: ApprovalStatus = "unreviewed"
    reused_check: bool = False
    check: CheckRecord | None = None
    template: dict[str, Any] | None = None
    qualification: Qualification | None = None
    findings: list[str] = Field(default_factory=list)
    created_at: str = Field(min_length=1)
    # Additive diagnostics for the viewer; the frozen fields above never move.
    scope: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    check_qualification: Qualification | None = None


class PilotQuestion(PilotModel):
    question: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    choices: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)
    answer: str = Field(min_length=1)
    parameters: dict[str, int | str] = Field(default_factory=dict)
    check_ref: CheckRef

    @model_validator(mode="after")
    def require_index_in_choices(self) -> PilotQuestion:
        if self.correct_index >= len(self.choices):
            raise ValueError("correct_index must address a choice")
        return self


class PilotBatch(PilotModel):
    template_id: str
    seed: int
    questions: list[PilotQuestion] = Field(default_factory=list)
    requested_quantity: int = Field(ge=1)
    shortfall: int = Field(ge=0)
    findings: list[str] = Field(default_factory=list)


class PolynomialScope(PilotModel):
    subject: Literal["univariate-real-polynomial"] = "univariate-real-polynomial"
    operation: Literal["differentiate"] = "differentiate"
    variable: Literal["x"] = "x"
    max_degree: int = Field(default=5, ge=0, le=5)
    max_abs_coefficient: int = Field(default=20, ge=1, le=1000)


SUPPORTED_SCOPE = PolynomialScope()


class RecipeArgument(PilotModel):
    source: Literal["input", "step", "literal"]
    name: str | None = Field(default=None, max_length=64)
    value: int | bool | str | None = None

    @model_validator(mode="after")
    def require_exactly_one_source_payload(self) -> RecipeArgument:
        if self.source in {"input", "step"}:
            if self.name is None or self.value is not None:
                raise ValueError(f"{self.source} arguments require only a name")
        elif self.value is None:
            raise ValueError("literal arguments require a value")
        elif self.name is not None:
            raise ValueError("literal arguments must not have a name")
        return self


class RecipeStep(PilotModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    arguments: dict[str, RecipeArgument] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def strip_null_argument_placeholders(cls, data: Any) -> Any:
        """Remove nullable wire placeholders before exact argument validation."""
        if isinstance(data, dict):
            arguments = data.get("arguments")
            if isinstance(arguments, dict):
                cleaned = {
                    name: value
                    for name, value in arguments.items()
                    if value is not None
                }
                if len(cleaned) != len(arguments):
                    data = {**data, "arguments": cleaned}
        return data


class CheckRecipeDefinition(PilotModel):
    schema_version: Literal["check-recipe/1"] = RECIPE_SCHEMA_VERSION
    operation_set: Literal["polynomial-derivative/1"] = RECIPE_OPERATION_SET
    steps: list[RecipeStep] = Field(min_length=1, max_length=8)
    output: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


class CoefficientDomain(PilotModel):
    exponent: int = Field(ge=0, le=5)
    values: list[int] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def require_bounded_unique_values(self) -> CoefficientDomain:
        if any(type(value) is not int for value in self.values):
            raise ValueError("coefficient domains require integers")
        if any(abs(value) > 20 for value in self.values):
            raise ValueError("coefficient values are bounded to [-20, 20]")
        if len(set(self.values)) != len(self.values):
            raise ValueError("coefficient domain values must be unique")
        return self


class PolynomialFamily(PilotModel):
    schema_version: Literal["polynomial-family/1"] = FAMILY_SCHEMA_VERSION
    variable: Literal["x"] = "x"
    degree: int = Field(ge=1, le=5)
    coefficients: list[CoefficientDomain] = Field(min_length=2, max_length=6)
    num_distractors: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def require_complete_bounded_domains(self) -> PolynomialFamily:
        exponents = [domain.exponent for domain in self.coefficients]
        if exponents != list(range(self.degree + 1)):
            raise ValueError(
                "coefficient domains must declare each exponent from 0 to degree"
            )
        leading = self.coefficients[-1]
        if 0 in leading.values:
            raise ValueError("the leading coefficient domain must not contain zero")
        size = math.prod(len(domain.values) for domain in self.coefficients)
        if size > 10_000_000:
            raise ValueError("the declared family is too large to sample safely")
        return self


class PilotTemplateDefinition(PilotModel):
    schema_version: Literal["pilot-template/1"] = TEMPLATE_SCHEMA_VERSION
    renderer_version: Literal["polynomial-mcq/1"] = RENDERER_VERSION
    scope: PolynomialScope = SUPPORTED_SCOPE
    family: PolynomialFamily


def _recipe_argument_names() -> list[str]:
    """Union of trusted operation input names, imported late to avoid a cycle."""
    from edcraft_validator.application.check_pilot.operations import (
        operation_catalogue,
    )

    names: set[str] = set()
    for descriptor in operation_catalogue():
        names.update(descriptor["inputs"])
    return sorted(names)


def _make_schema_strict(node: object) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in node.values():
            _make_schema_strict(value)
    elif isinstance(node, list):
        for value in node:
            _make_schema_strict(value)


def _strict_author_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Close every object shape in one author-proposal schema for strict mode."""
    definitions = schema.get("$defs")
    if isinstance(definitions, dict):
        step = definitions.get("RecipeStep")
        if isinstance(step, dict):
            properties = step.get("properties")
            if isinstance(properties, dict):
                names = _recipe_argument_names()
                properties["arguments"] = {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        name: {
                            "anyOf": [
                                {"$ref": "#/$defs/RecipeArgument"},
                                {"type": "null"},
                            ]
                        }
                        for name in names
                    },
                    "required": names,
                }
    _make_schema_strict(schema)
    return schema


class _StrictAuthorProposalSchema:
    """Override applied only to the two model-facing author proposal schemas."""

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # The concrete model supplies model_json_schema; this mixin is only ever
        # used as a base class alongside PilotModel.
        schema = super().model_json_schema(*args, **kwargs)  # type: ignore[misc]
        return _strict_author_schema(schema)


class CheckAuthorProposal(_StrictAuthorProposalSchema, PilotModel):
    supported: bool = True
    development_needed: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    recipe: CheckRecipeDefinition | None = None

    @model_validator(mode="after")
    def require_supported_payload(self) -> CheckAuthorProposal:
        if self.supported:
            if self.recipe is None or not self.title or not self.description:
                raise ValueError(
                    "a supported check proposal requires title, description and recipe"
                )
        elif not (self.development_needed or "").strip():
            raise ValueError("an unsupported proposal requires development_needed")
        return self


class TemplateAuthorProposal(_StrictAuthorProposalSchema, PilotModel):
    supported: bool = True
    development_needed: str | None = Field(default=None, max_length=1000)
    family: PolynomialFamily | None = None

    @model_validator(mode="after")
    def require_supported_payload(self) -> TemplateAuthorProposal:
        if self.supported and self.family is None:
            raise ValueError("a supported template proposal requires a family")
        if not self.supported and not (self.development_needed or "").strip():
            raise ValueError("an unsupported proposal requires development_needed")
        return self


class PilotQualificationSettings(PilotModel):
    max_examples: int = Field(default=50, ge=4, le=200)
    max_execution_calls: int = Field(default=1200, ge=1, le=10_000)
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @model_validator(mode="after")
    def require_finite_timeout(self) -> PilotQualificationSettings:
        if not math.isfinite(self.timeout_seconds):
            raise ValueError("qualification timeout must be finite")
        return self


class RecipeExecutionResult(PilotModel):
    verdict: bool
    expected: str
    problem: str
    candidate: str
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "ApprovalStatus",
    "CHECK_SCHEMA_VERSION",
    "CheckAuthorProposal",
    "CheckRecipeDefinition",
    "CheckRecord",
    "CheckRef",
    "CoefficientDomain",
    "FAMILY_SCHEMA_VERSION",
    "MAX_RECIPE_CASES",
    "PilotBatch",
    "PilotModel",
    "PilotQualificationSettings",
    "PilotQuestion",
    "PilotTemplateDefinition",
    "PilotTemplateRecord",
    "PolynomialFamily",
    "PolynomialScope",
    "Qualification",
    "QualificationStatus",
    "RECIPE_OPERATION_SET",
    "RECIPE_SCHEMA_VERSION",
    "RENDERER_VERSION",
    "RecipeArgument",
    "RecipeExecutionResult",
    "RecipeStep",
    "SUPPORTED_SCOPE",
    "TEMPLATE_SCHEMA_VERSION",
    "TemplateAuthorProposal",
    "TemplateStatus",
]
