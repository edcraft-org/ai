"""Typed, closed-vocabulary math IR.

The IR is the source of truth for one math item. It is data, never code: the
model may only emit the fields and operators declared here. The compiler in
``compile.py`` turns an IR into SymPy expressions internally.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.text_templates import template_fields

IR_VERSION: Literal["math-ir/0.1"] = "math-ir/0.1"

# Text placeholders the renderer supplies in addition to declared parameters.
RESERVED_TEXT_FIELDS = frozenset({"expr", "equation", "equations", "matrix"})

Domain = Literal["real", "integer", "rational"]
RelationKind = Literal["eq", "ne", "lt", "le", "gt", "ge"]
GoalKind = Literal[
    "evaluate",
    "solve",
    "simplify",
    "factor",
    "expand",
    "derivative",
    "integral",
    "limit",
    "determinant",
    "eigenvalues",
]
AnswerKind = Literal[
    "numeric", "expression", "set", "interval", "tuple", "matrix", "boolean"
]
PrimitiveKind = Literal[
    "numeric",
    "expression_equiv",
    "solution_set",
    "collection",
    "interval",
    "quantity",
    "matrix_vector",
    "string_choice",
    "proof",
]
TextMode = Literal["symbolic", "prose"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Expr(Record):
    """One node of the closed expression tree.

    Exactly one of ``num``, ``sym``, ``param`` or ``op`` is set. ``num`` is an
    exact decimal or rational literal and is never parsed as a float.
    """

    num: str | None = Field(default=None, min_length=1)
    sym: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    param: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    op: str | None = Field(default=None, min_length=1)
    args: list[Expr] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_one_node_kind(self) -> Expr:
        kinds = [
            self.num is not None,
            self.sym is not None,
            self.param is not None,
            self.op is not None,
        ]
        if sum(kinds) != 1:
            raise ValueError("an expression node sets exactly one of num/sym/param/op")
        if self.op is None and self.args:
            raise ValueError("only operator nodes may have arguments")
        return self


Expr.model_rebuild()


class SymbolSpec(Record):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    kind: Literal["unknown", "given"] = "unknown"
    domain: Domain = "real"
    positive: bool = False
    nonzero: bool = False
    integer: bool = False


class Relation(Record):
    kind: RelationKind = "eq"
    lhs: Expr
    rhs: Expr


class Given(Record):
    """A declared fact: a relation, a symbol domain, or a finite data set."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    kind: Literal["relation", "domain", "dataset"] = "relation"
    relation: Relation | None = None
    symbol: str | None = None
    domain: Domain | None = None
    values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_payload(self) -> Given:
        if self.kind == "relation" and self.relation is None:
            raise ValueError("relation givens require a relation")
        if self.kind == "domain" and (self.symbol is None or self.domain is None):
            raise ValueError("domain givens require a symbol and domain")
        if self.kind == "dataset" and not self.values:
            raise ValueError("dataset givens require values")
        return self


class Goal(Record):
    kind: GoalKind
    symbol: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    symbols: list[str] = Field(default_factory=list)
    expr: Expr | None = None
    point: Expr | None = None
    order: int = Field(default=1, ge=1, le=8)
    domain: Domain = "real"
    matrix: list[list[Expr]] | None = None

    @model_validator(mode="after")
    def require_payload(self) -> Goal:
        if self.kind == "solve" and not (self.symbol or self.symbols):
            raise ValueError("solve goals require a symbol or symbols")
        if (
            self.kind
            in {
                "evaluate",
                "simplify",
                "factor",
                "expand",
                "derivative",
                "integral",
                "limit",
            }
            and self.expr is None
        ):
            raise ValueError(f"{self.kind} goals require an expression")
        if self.kind == "limit" and self.point is None:
            raise ValueError("limit goals require a point")
        if self.kind in {"determinant", "eigenvalues"} and not self.matrix:
            raise ValueError(f"{self.kind} goals require a matrix")
        if self.kind == "solve" and self.symbol is not None and self.symbols:
            raise ValueError("solve goals use either symbol or symbols, not both")
        return self


class Interval(Record):
    lower: str | None = None
    upper: str | None = None
    lower_open: bool = True
    upper_open: bool = True


class Answer(Record):
    """A derived answer. Validation compares SymPy objects, not this display."""

    kind: AnswerKind
    items: list[str] = Field(default_factory=list)
    interval: Interval | None = None
    matrix: list[list[str]] | None = None
    boolean: bool | None = None
    display: str = ""


class Distractor(Record):
    value: Expr | None = None
    items: list[Expr] = Field(default_factory=list)
    components: list[Expr] = Field(default_factory=list)
    misconception: str = Field(min_length=1)
    reason: str = ""

    @model_validator(mode="after")
    def require_value(self) -> Distractor:
        supplied = sum(
            (
                self.value is not None,
                bool(self.items),
                bool(self.components),
            )
        )
        if supplied != 1:
            raise ValueError(
                "a distractor requires exactly one of value, items, or components"
            )
        return self


class TextSpec(Record):
    mode: TextMode = "symbolic"
    template: str = Field(min_length=1)
    anchors: dict[str, tuple[int, int]] = Field(default_factory=dict)


class PrimitiveSpec(Record):
    type: PrimitiveKind
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ValidationSpec(Record):
    primitives: list[PrimitiveSpec] = Field(min_length=1)


class MathItemSpec(Record):
    """One concrete item, optionally with a derived answer attached."""

    schema_version: Literal["math-ir/0.1"] = IR_VERSION
    topic: str = Field(min_length=1)
    symbols: list[SymbolSpec] = Field(min_length=1)
    givens: list[Given] = Field(min_length=1)
    goal: Goal
    answer: Answer | None = None
    distractors: list[Distractor] = Field(default_factory=list)
    text: TextSpec
    validation: ValidationSpec

    @model_validator(mode="after")
    def require_unique_names(self) -> MathItemSpec:
        names = [symbol.name for symbol in self.symbols]
        if len(names) != len(set(names)):
            raise ValueError("symbol names must be unique")
        known = set(names)
        for given in self.givens:
            if given.kind == "domain" and given.symbol not in known:
                raise ValueError(
                    f"domain given references unknown symbol {given.symbol!r}"
                )
        if self.goal.symbol is not None and self.goal.symbol not in known:
            raise ValueError(f"goal references unknown symbol {self.goal.symbol!r}")
        for name in self.goal.symbols:
            if name not in known:
                raise ValueError(f"goal references unknown symbol {name!r}")
        return self


class ParameterSpec(Record):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    values: list[str] = Field(min_length=1, max_length=32)


def _expr_parameters(expr: Expr | None) -> set[str]:
    if expr is None:
        return set()
    found = {expr.param} if expr.param is not None else set()
    for child in expr.args:
        found.update(_expr_parameters(child))
    return found


def _relation_parameters(relation: Relation | None) -> set[str]:
    if relation is None:
        return set()
    return _expr_parameters(relation.lhs) | _expr_parameters(relation.rhs)


def item_parameters(item: MathItemSpec) -> set[str]:
    """Return every parameter name referenced by an item body."""
    found: set[str] = set()
    for given in item.givens:
        found.update(_relation_parameters(given.relation))
    found.update(_expr_parameters(item.goal.expr))
    found.update(_expr_parameters(item.goal.point))
    for row in item.goal.matrix or []:
        for cell in row:
            found.update(_expr_parameters(cell))
    for distractor in item.distractors:
        found.update(_expr_parameters(distractor.value))
        for entry in [*distractor.items, *distractor.components]:
            found.update(_expr_parameters(entry))
    return found


class MathTemplateSpec(Record):
    """A reusable item family: a body with parameter nodes plus finite values."""

    schema_version: Literal["math-ir/0.1"] = IR_VERSION
    topic: str = Field(min_length=1)
    parameters: list[ParameterSpec] = Field(min_length=1, max_length=6)
    body: MathItemSpec

    @model_validator(mode="after")
    def require_declared_parameters(self) -> MathTemplateSpec:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("template parameter names must be unique")
        declared = set(names)
        used = item_parameters(self.body)
        unknown = sorted(used - declared)
        if unknown:
            raise ValueError(
                "body references undeclared parameters: " + ", ".join(unknown)
            )
        fields = template_fields(self.body.text.template)
        unknown_fields = sorted(fields - declared - RESERVED_TEXT_FIELDS)
        if unknown_fields:
            raise ValueError(
                "text template uses unsupported placeholders: "
                + ", ".join(unknown_fields)
            )
        return self


class MathReconstruction(Record):
    """Blind parse-back output: the problem the text appears to state."""

    topic: str = Field(min_length=1)
    symbols: list[SymbolSpec] = Field(min_length=1)
    givens: list[Given] = Field(min_length=1)
    goal: Goal
    ambiguous: bool = False
    ambiguities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_abstention_reason(self) -> MathReconstruction:
        if self.ambiguous and not self.ambiguities:
            raise ValueError("ambiguous reconstructions require at least one reason")
        return self
