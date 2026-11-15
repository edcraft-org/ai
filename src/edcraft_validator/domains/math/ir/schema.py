"""Typed, closed-vocabulary math IR.

The IR is the source of truth for one math item. It is data, never code: the
model may only emit the fields and operators declared here. The compiler in
``compile.py`` turns an IR into SymPy expressions internally.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.text_templates import template_fields

IR_VERSION: Literal["math-ir/0.1"] = "math-ir/0.1"

# Text placeholders the renderer supplies in addition to declared parameters.
RESERVED_TEXT_FIELDS = frozenset({"expr", "equation", "equations", "matrix"})


def _is_rectangular(matrix: list[list[Expr]]) -> bool:
    """Whether ``matrix`` has at least one row/column and every row matches."""
    if not matrix:
        return False
    width = len(matrix[0])
    return width > 0 and all(len(row) == width for row in matrix)


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
        if self.matrix is not None and not _is_rectangular(self.matrix):
            raise ValueError("goal matrices must be non-empty and rectangular")
        if self.kind == "solve" and self.symbol is not None and self.symbols:
            raise ValueError("solve goals use either symbol or symbols, not both")

        return self


class RecipeInterval(Record):
    lower: Expr | None = None
    upper: Expr | None = None
    lower_open: bool = True
    upper_open: bool = True


class AnswerRecipe(Record):
    """A structured answer authored as typed expression trees.

    The model authors recipes the same way it authors distractors: closed
    ``Expr`` nodes, optionally with parameter references. The deterministic
    engine compiles them later; ``display`` is never compared.
    """

    kind: AnswerKind
    items: list[Expr] = Field(default_factory=list)
    interval: RecipeInterval | None = None
    matrix: list[list[Expr]] | None = None
    boolean: bool | None = None
    display: str = ""

    @model_validator(mode="after")
    def require_payload(self) -> AnswerRecipe:
        if self.kind in {"numeric", "expression"}:
            if len(self.items) != 1:
                raise ValueError(f"{self.kind} answer recipes require exactly one item")
        elif self.kind in {"set", "tuple"}:
            if not self.items:
                raise ValueError(
                    f"{self.kind} answer recipes require at least one item"
                )
        elif self.kind == "interval":
            if self.interval is None:
                raise ValueError("interval answer recipes require an interval value")
        elif self.kind == "matrix":
            if self.matrix is None:
                raise ValueError("matrix answer recipes require a matrix value")
            if not _is_rectangular(self.matrix):
                raise ValueError("matrix answer recipes require a rectangular matrix")
        elif self.kind == "boolean":
            if self.boolean is None:
                raise ValueError("boolean answer recipes require a boolean value")

        primary = {
            "numeric": "items",
            "expression": "items",
            "set": "items",
            "tuple": "items",
            "interval": "interval",
            "matrix": "matrix",
            "boolean": "boolean",
        }[self.kind]

        payload = {
            "items": bool(self.items),
            "interval": self.interval is not None,
            "matrix": self.matrix is not None,
            "boolean": self.boolean is not None,
        }
        extra = sorted(
            name for name, present in payload.items() if name != primary and present
        )

        if extra:
            raise ValueError(
                f"{self.kind} answer recipes must not set: " + ", ".join(extra)
            )
        return self


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


class MathItemSpec(Record):
    """One concrete item with the answer recipe that the engine grades.

    The recipe is the only answer representation: correctness is decided by the
    deterministic engine and shape by the form registry. Nothing derives a key.
    """

    schema_version: Literal["math-ir/0.1"] = IR_VERSION
    topic: str = Field(min_length=1)
    symbols: list[SymbolSpec] = Field(min_length=1)
    givens: list[Given] = Field(min_length=1)
    goal: Goal
    answer_recipe: AnswerRecipe | None = None
    distractors: list[Distractor] = Field(default_factory=list)
    text: TextSpec

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
    """One named axis of a template's declared, finite parameter domain."""

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    # The declared domain may be far larger than the validation sample. The
    # per-axis and parameter-count limits only keep authored JSON bounded.
    values: list[str] = Field(min_length=1, max_length=512)


def _expr_nodes(expr: Expr | None) -> Iterator[Expr]:
    if expr is None:
        return
    yield expr
    for child in expr.args:
        yield from _expr_nodes(child)


def _item_expr_nodes(item: MathItemSpec) -> Iterator[Expr]:
    for given in item.givens:
        if given.relation is not None:
            yield from _expr_nodes(given.relation.lhs)
            yield from _expr_nodes(given.relation.rhs)
    yield from _expr_nodes(item.goal.expr)
    yield from _expr_nodes(item.goal.point)
    for row in item.goal.matrix or []:
        for cell in row:
            yield from _expr_nodes(cell)

    recipe = item.answer_recipe
    if recipe is not None:
        for entry in recipe.items:
            yield from _expr_nodes(entry)
        for row in recipe.matrix or []:
            for cell in row:
                yield from _expr_nodes(cell)
        if recipe.interval is not None:
            yield from _expr_nodes(recipe.interval.lower)
            yield from _expr_nodes(recipe.interval.upper)

    for distractor in item.distractors:
        yield from _expr_nodes(distractor.value)
        for entry in [*distractor.items, *distractor.components]:
            yield from _expr_nodes(entry)


def item_parameters(item: MathItemSpec) -> set[str]:
    """Return every parameter name referenced by an item body."""
    return {node.param for node in _item_expr_nodes(item) if node.param is not None}


def item_symbols(item: MathItemSpec) -> set[str]:
    """Return every symbol name referenced by an item body."""
    return {node.sym for node in _item_expr_nodes(item) if node.sym is not None}


class MathTemplateSpec(Record):
    """A reusable item family: a body with parameter nodes plus finite values."""

    schema_version: Literal["math-ir/0.1"] = IR_VERSION
    topic: str = Field(min_length=1)
    parameters: list[ParameterSpec] = Field(min_length=1, max_length=12)
    body: MathItemSpec

    @model_validator(mode="after")
    def require_declared_parameters(self) -> MathTemplateSpec:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("template parameter names must be unique")

        declared = set(names)
        ambiguous = sorted(declared & item_symbols(self.body))
        if ambiguous:
            raise ValueError(
                "parameters must not also be referenced as symbols: "
                + ", ".join(ambiguous)
            )

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
        unused = sorted(declared - used - (fields - RESERVED_TEXT_FIELDS))
        if unused:
            raise ValueError(
                "template declares parameters that are never used: " + ", ".join(unused)
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
