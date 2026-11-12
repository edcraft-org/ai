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
SOLVE_FAMILY_SCHEMA_VERSION: Literal["polynomial-solve-family/1"] = (
    "polynomial-solve-family/1"
)
TEMPLATE_SCHEMA_VERSION: Literal["pilot-template/1"] = "pilot-template/1"
TEMPLATE_SCHEMA_VERSION_V2: Literal["pilot-template/2"] = "pilot-template/2"
RECIPE_OPERATION_SET: Literal["polynomial-derivative/1"] = "polynomial-derivative/1"
SOLVE_RECIPE_OPERATION_SET: Literal["polynomial-solve-real/1"] = (
    "polynomial-solve-real/1"
)
RENDERER_VERSION: Literal["polynomial-mcq/1"] = "polynomial-mcq/1"
SOLVE_RENDERER_VERSION: Literal["polynomial-solve-mcq/1"] = "polynomial-solve-mcq/1"
SCOPE_SCHEMA_VERSION: Literal["check-scope/2"] = "check-scope/2"
MAX_RECIPE_CASES = 600
MAX_SOLVE_DEGREE = 2
MAX_RELATION_COEFFICIENT = 1000
MAX_SET_COMPONENTS = 8
MAX_ENDPOINT_LENGTH = 80

QualificationStatus = Literal["passed", "failed", "inconclusive", "error"]
QualificationPhase = Literal["compilation", "sampling"]
TemplateStatus = Literal["ready", "needs_review", "error"]
ApprovalStatus = Literal["unreviewed", "approved", "rejected"]
RelationKind = Literal["eq", "lt", "le", "gt", "ge"]
GoalRelation = Literal["none", "eq", "lt", "le", "gt", "ge"]
RequiredPolicy = Literal[
    "complete_correctness",
    "complete_real_solution_set",
    "independent_correctness",
    "all_options_checked",
]


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
    phase: QualificationPhase = "sampling"
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


class CheckSelection(PilotModel):
    """Additive UI metadata for the contract chosen for one template."""

    contract_id: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)
    source: Literal["saved", "authored"]
    check_ref: CheckRef | None = None


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
    selection: CheckSelection | None = None


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


class ContractScope(PilotModel):
    """Contract-level scope stored on new immutable check records."""

    schema_version: Literal["check-scope/2"] = SCOPE_SCHEMA_VERSION
    contract_id: str = Field(min_length=1, max_length=120)
    subject: Literal["univariate-real-polynomial"] = "univariate-real-polynomial"
    operation: Literal["differentiate", "solve"]
    variable: Literal["x"] = "x"
    relations: list[GoalRelation] = Field(min_length=1, max_length=6)
    min_degree: int = Field(ge=0, le=5)
    max_degree: int = Field(ge=0, le=5)
    max_abs_coefficient: int = Field(ge=1, le=1000)
    domain: Literal["real"] = "real"
    answer_type: Literal["expression", "solution_set"]
    required_policy: list[RequiredPolicy] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def require_ordered_bounds(self) -> ContractScope:
        if self.min_degree > self.max_degree:
            raise ValueError("min_degree must not exceed max_degree")
        if len(set(self.relations)) != len(self.relations):
            raise ValueError("scope relations must be unique")
        return self


class StructuredGoal(PilotModel):
    """The mathematical task a plan or template actually asks for."""

    subject: Literal["univariate-real-polynomial"] = "univariate-real-polynomial"
    operation: Literal["differentiate", "solve"]
    variable: Literal["x"] = "x"
    relation: GoalRelation = "none"
    min_degree: int = Field(ge=0, le=5)
    max_degree: int = Field(ge=0, le=5)
    max_abs_coefficient: int = Field(ge=1, le=1000)
    domain: Literal["real"] = "real"
    answer_type: Literal["expression", "solution_set"]
    requires_complete_solution_set: bool = False

    @model_validator(mode="after")
    def require_ordered_bounds(self) -> StructuredGoal:
        if self.min_degree > self.max_degree:
            raise ValueError("min_degree must not exceed max_degree")
        if self.operation == "differentiate":
            if self.relation != "none" or self.answer_type != "expression":
                raise ValueError("differentiate goals use relation none and expression")
            if self.requires_complete_solution_set:
                raise ValueError("differentiate goals do not request solution sets")
        else:
            if self.relation == "none" or self.answer_type != "solution_set":
                raise ValueError("solve goals use a relation and solution_set answer")
        return self


class PolynomialRelation(PilotModel):
    """A bounded real polynomial relation in ascending coefficient order."""

    relation: RelationKind
    coefficients: list[int] = Field(min_length=1, max_length=MAX_SOLVE_DEGREE + 1)
    variable: Literal["x"] = "x"

    @model_validator(mode="after")
    def require_bounded_coefficients(self) -> PolynomialRelation:
        if any(type(value) is not int for value in self.coefficients):
            raise ValueError("relation coefficients must be integers")
        if any(abs(value) > MAX_RELATION_COEFFICIENT for value in self.coefficients):
            raise ValueError("relation coefficients are out of bounds")
        if not any(self.coefficients):
            # The zero polynomial is still a valid constant relation.
            return self
        return self


class RealSetComponent(PilotModel):
    """One exact point or interval of a real solution-set union."""

    lower: str | None = Field(default=None, max_length=MAX_ENDPOINT_LENGTH)
    upper: str | None = Field(default=None, max_length=MAX_ENDPOINT_LENGTH)
    lower_closed: bool = True
    upper_closed: bool = True

    @model_validator(mode="after")
    def require_consistent_infinite_flags(self) -> RealSetComponent:
        if self.lower is None and self.upper is None:
            if self.lower_closed or self.upper_closed:
                raise ValueError("an all-real interval is unbounded at both ends")
            return self
        if self.lower is None and self.lower_closed:
            raise ValueError("an unbounded lower endpoint must be open")
        if self.upper is None and self.upper_closed:
            raise ValueError("an unbounded upper endpoint must be open")
        return self


class RealSolutionSet(PilotModel):
    """Closed data for a complete real solution set; empty means no solutions."""

    components: list[RealSetComponent] = Field(
        default_factory=list, max_length=MAX_SET_COMPONENTS
    )


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
    operation_set: Literal["polynomial-derivative/1", "polynomial-solve-real/1"] = (
        RECIPE_OPERATION_SET
    )
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


class SolveFamily(PilotModel):
    schema_version: Literal["polynomial-solve-family/1"] = SOLVE_FAMILY_SCHEMA_VERSION
    variable: Literal["x"] = "x"
    relation: RelationKind
    degree: int = Field(ge=1, le=MAX_SOLVE_DEGREE)
    coefficients: list[CoefficientDomain] = Field(min_length=2, max_length=3)
    num_distractors: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def require_complete_bounded_domains(self) -> SolveFamily:
        exponents = [domain.exponent for domain in self.coefficients]
        if exponents != list(range(self.degree + 1)):
            raise ValueError(
                "coefficient domains must declare each exponent from 0 to degree"
            )
        leading = self.coefficients[-1]
        if 0 in leading.values:
            raise ValueError("the leading coefficient domain must not contain zero")
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
    schema_version: Literal["pilot-template/1", "pilot-template/2"] = (
        TEMPLATE_SCHEMA_VERSION
    )
    renderer_version: Literal["polynomial-mcq/1", "polynomial-solve-mcq/1"] = (
        RENDERER_VERSION
    )
    scope: PolynomialScope | ContractScope = SUPPORTED_SCOPE
    contract_id: str | None = Field(default=None, max_length=120)
    family: PolynomialFamily | None = None
    solve_family: SolveFamily | None = None

    @model_validator(mode="after")
    def require_one_supported_payload(self) -> PilotTemplateDefinition:
        if self.schema_version == "pilot-template/1":
            if self.contract_id is not None or self.solve_family is not None:
                raise ValueError("legacy templates use only a polynomial family")
            if self.family is None or not isinstance(self.scope, PolynomialScope):
                raise ValueError("legacy templates require a polynomial family")
            if self.renderer_version != RENDERER_VERSION:
                raise ValueError("legacy templates use the polynomial renderer")
            return self
        if not self.contract_id:
            raise ValueError("version 2 templates require a contract id")
        if not isinstance(self.scope, ContractScope):
            raise ValueError("version 2 templates require a contract scope")
        if self.scope.contract_id != self.contract_id:
            raise ValueError("template contract id must match its scope")
        if (self.family is None) == (self.solve_family is None):
            raise ValueError("version 2 templates require exactly one family kind")
        if self.family is not None and self.scope.operation != "differentiate":
            raise ValueError("polynomial families require a differentiate contract")
        if self.solve_family is not None and self.scope.operation != "solve":
            raise ValueError("solve families require a solve contract")
        return self


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


class CheckPlanProposal(_StrictAuthorProposalSchema, PilotModel):
    supported: bool = True
    development_needed: str | None = Field(default=None, max_length=1000)
    contract_id: str | None = Field(default=None, max_length=120)
    goal: StructuredGoal | None = None
    reason: str = Field(default="", max_length=2000)
    saved_check_ref: CheckRef | None = None

    @model_validator(mode="after")
    def require_supported_plan(self) -> CheckPlanProposal:
        if self.supported:
            if not self.contract_id or self.goal is None:
                raise ValueError(
                    "a supported plan requires a contract id and structured goal"
                )
            if not self.reason.strip():
                raise ValueError("a supported plan requires a reason")
        elif not (self.development_needed or "").strip():
            raise ValueError("an unsupported plan requires development_needed")
        return self


class TemplateAuthorProposal(_StrictAuthorProposalSchema, PilotModel):
    supported: bool = True
    development_needed: str | None = Field(default=None, max_length=1000)
    contract_id: str | None = Field(default=None, max_length=120)
    reason: str = Field(default="", max_length=2000)
    family: PolynomialFamily | None = None
    solve_family: SolveFamily | None = None

    @model_validator(mode="after")
    def require_supported_payload(self) -> TemplateAuthorProposal:
        if self.supported:
            if (self.family is None) == (self.solve_family is None):
                raise ValueError(
                    "a supported template proposal requires exactly one family"
                )
            if self.solve_family is not None and not self.contract_id:
                raise ValueError("solve templates require a contract id")
        elif not (self.development_needed or "").strip():
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
    "CheckPlanProposal",
    "CheckRecipeDefinition",
    "CheckRecord",
    "CheckRef",
    "CheckSelection",
    "CoefficientDomain",
    "ContractScope",
    "FAMILY_SCHEMA_VERSION",
    "GoalRelation",
    "MAX_ENDPOINT_LENGTH",
    "MAX_RECIPE_CASES",
    "MAX_RELATION_COEFFICIENT",
    "MAX_SET_COMPONENTS",
    "MAX_SOLVE_DEGREE",
    "PilotBatch",
    "PilotModel",
    "PilotQualificationSettings",
    "PilotQuestion",
    "PilotTemplateDefinition",
    "PilotTemplateRecord",
    "PolynomialFamily",
    "PolynomialRelation",
    "PolynomialScope",
    "Qualification",
    "QualificationStatus",
    "RECIPE_OPERATION_SET",
    "RECIPE_SCHEMA_VERSION",
    "RENDERER_VERSION",
    "RealSetComponent",
    "RealSolutionSet",
    "RecipeArgument",
    "RecipeExecutionResult",
    "RecipeStep",
    "RelationKind",
    "RequiredPolicy",
    "SCOPE_SCHEMA_VERSION",
    "SOLVE_FAMILY_SCHEMA_VERSION",
    "SOLVE_RECIPE_OPERATION_SET",
    "SOLVE_RENDERER_VERSION",
    "SUPPORTED_SCOPE",
    "SolveFamily",
    "StructuredGoal",
    "TEMPLATE_SCHEMA_VERSION",
    "TEMPLATE_SCHEMA_VERSION_V2",
    "TemplateAuthorProposal",
    "TemplateStatus",
]
