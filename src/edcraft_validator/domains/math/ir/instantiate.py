"""Render one finite math IR template into learner-facing text and choices.

The template body is data: parameter nodes are the only variation point. This
module substitutes declared values for display and compilation, and it renders
the reserved placeholders ``expr``, ``equation``, ``equations`` and ``matrix``.
It never executes model-authored code.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from itertools import product

import sympy
from sympy.matrices.matrixbase import MatrixBase

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
    compile_relation,
)
from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Expr,
    MathItemSpec,
    MathTemplateSpec,
    Relation,
)
from edcraft_validator.text_templates import render_text_template, template_fields


def fraction_text(value: Fraction | int) -> str:
    """Render an exact value without a trailing decimal or float conversion."""
    fraction = value if isinstance(value, Fraction) else Fraction(value)
    if fraction.denominator == 1:
        return str(fraction.numerator)
    return f"{fraction.numerator}/{fraction.denominator}"


def render_expr(value: sympy.Expr) -> str:
    """Render an exact SymPy value in the lightweight notation used in prompts."""
    return sympy.sstr(value).replace("**", "^")


def render_relation(
    relation: Relation,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    compiled = compile_relation(relation, symbols, params)
    operator = {
        "eq": "=",
        "ne": "≠",
        "lt": "<",
        "le": "≤",
        "gt": ">",
        "ge": "≥",
    }[relation.kind]
    return f"{render_expr(compiled.lhs)} {operator} {render_expr(compiled.rhs)}"


def render_matrix(
    rows: list[list[Expr]],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    rendered = [
        "["
        + ", ".join(render_expr(compile_expr(cell, symbols, params)) for cell in row)
        + "]"
        for row in rows
    ]
    return "[" + ", ".join(rendered) + "]"


def render_relations(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> list[str]:
    symbols = build_symbols(item.symbols)
    return [
        render_relation(given.relation, symbols, params)
        for given in item.givens
        if given.kind == "relation" and given.relation is not None
    ]


def render_goal_display(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Render the mathematical object the learner is asked about."""
    relations = render_relations(item, params)
    if relations:
        return " and ".join(relations)
    symbols = build_symbols(item.symbols)
    if item.goal.kind == "evaluate":
        # An evaluate goal often encodes the arithmetic itself, so the authored
        # text is the problem and the solved value is not a display.
        return render_item_text(item, params)
    if item.goal.expr is not None:
        rendered = render_expr(compile_expr(item.goal.expr, symbols, params))
        if item.goal.kind in {"derivative", "integral"} and item.goal.symbol:
            return f"f({item.goal.symbol}) = {rendered}"
        return rendered
    if item.goal.matrix:
        return render_matrix(item.goal.matrix, symbols, params)
    return render_item_text(item, params)


def render_item_text(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Fill a template's learner-facing text without solving the item."""
    fields = template_fields(item.text.template)
    values: dict[str, str] = {
        name: fraction_text(value) for name, value in (params or {}).items()
    }
    symbols = build_symbols(item.symbols)
    relations = render_relations(item, params)
    if fields & {"expr"}:
        if item.goal.expr is None:
            raise ValueError("text template uses {{expr}} but the goal has none")
        values["expr"] = render_expr(compile_expr(item.goal.expr, symbols, params))
    if fields & {"equation", "equations"}:
        if not relations:
            raise ValueError("text template uses an equation but the item has none")
        values["equation"] = relations[0]
        values["equations"] = " and ".join(relations)
    if "matrix" in fields:
        if not item.goal.matrix:
            raise ValueError("text template uses {{matrix}} but the goal has none")
        values["matrix"] = render_matrix(item.goal.matrix, symbols, params)
    return render_text_template(item.text.template, values)


def substitute_expr(expr: Expr, params: Mapping[str, Fraction]) -> Expr:
    """Replace parameter nodes with exact numeric literals."""
    if expr.param is not None:
        try:
            value = params[expr.param]
        except KeyError as exc:
            raise ValueError(f"unbound parameter {expr.param!r}") from exc
        return Expr(num=fraction_text(value))
    if expr.op is None:
        return expr
    return expr.model_copy(
        update={"args": [substitute_expr(child, params) for child in expr.args]}
    )


def substitute_item(item: MathItemSpec, params: Mapping[str, Fraction]) -> MathItemSpec:
    """Return a concrete item with every parameter node replaced by its value."""
    givens = []
    for given in item.givens:
        relation = given.relation
        if relation is not None:
            relation = relation.model_copy(
                update={
                    "lhs": substitute_expr(relation.lhs, params),
                    "rhs": substitute_expr(relation.rhs, params),
                }
            )
        givens.append(given.model_copy(update={"relation": relation}))
    goal = item.goal.model_copy(
        update={
            "expr": (
                substitute_expr(item.goal.expr, params)
                if item.goal.expr is not None
                else None
            ),
            "point": (
                substitute_expr(item.goal.point, params)
                if item.goal.point is not None
                else None
            ),
            "matrix": (
                [
                    [substitute_expr(cell, params) for cell in row]
                    for row in item.goal.matrix
                ]
                if item.goal.matrix is not None
                else None
            ),
        }
    )
    distractors = [
        distractor.model_copy(
            update={
                "value": (
                    substitute_expr(distractor.value, params)
                    if distractor.value is not None
                    else None
                ),
                "items": [substitute_expr(entry, params) for entry in distractor.items],
                "components": [
                    substitute_expr(entry, params) for entry in distractor.components
                ],
            }
        )
        for distractor in item.distractors
    ]
    return item.model_copy(
        update={
            "givens": givens,
            "goal": goal,
            "distractors": distractors,
            "text": item.text.model_copy(
                update={"template": render_item_text(item, params)}
            ),
        }
    )


def parameter_combinations(
    template: MathTemplateSpec,
) -> list[dict[str, Fraction]]:
    """Enumerate the finite parameter grid, skipping invalid literals."""
    names = [parameter.name for parameter in template.parameters]
    combinations: list[dict[str, Fraction]] = []
    for values in product(*(parameter.values for parameter in template.parameters)):
        try:
            combinations.append(
                dict(zip(names, (Fraction(value) for value in values), strict=True))
            )
        except (ValueError, ZeroDivisionError):
            continue
    return combinations


def representative_item(template: MathTemplateSpec) -> MathItemSpec:
    """Instantiate the first renderable combination for a concrete check.

    Prose fidelity and blind parse-back operate on a concrete item, not on
    unbound parameter nodes. Symbolic templates use the same projection for
    consistency; their parse-back is skipped.
    """
    for params in parameter_combinations(template):
        try:
            return substitute_item(template.body, params)
        except (MathCompileError, ValueError, ZeroDivisionError):
            continue
    raise ValueError("template has no renderable parameter combination")


def display_sympy_value(value: object) -> str:
    """Render a solved value using the same notation as the question text."""
    if isinstance(value, MatrixBase):
        return (
            "[["
            + ", ".join(
                ", ".join(render_expr(cell) for cell in row) for row in value.tolist()
            )
            + "]]"
        )
    if isinstance(value, sympy.Tuple):
        return "(" + ", ".join(render_expr(item) for item in value) + ")"
    if isinstance(value, sympy.FiniteSet):
        items = sorted(value.args, key=sympy.default_sort_key)
        return "{" + ", ".join(display_sympy_value(item) for item in items) + "}"
    if isinstance(value, sympy.Interval):
        return sympy.sstr(value).replace("**", "^")
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, sympy.Expr):
        return render_expr(value)
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(display_sympy_value(item) for item in value) + ")"
    return str(value)


def compile_distractor_value(
    item: MathItemSpec,
    distractor: Distractor,
    params: Mapping[str, Fraction] | None = None,
) -> object:
    """Compile one distractor for display or comparison."""
    symbols = build_symbols(item.symbols)
    if distractor.value is not None:
        return compile_expr(distractor.value, symbols, params)
    if distractor.components:
        return sympy.Tuple(
            *[compile_expr(entry, symbols, params) for entry in distractor.components]
        )
    return sympy.FiniteSet(
        *[compile_expr(entry, symbols, params) for entry in distractor.items]
    )


def display_distractor(
    item: MathItemSpec,
    distractor: Distractor,
    params: Mapping[str, Fraction] | None = None,
) -> str:
    return display_sympy_value(compile_distractor_value(item, distractor, params))


__all__ = [
    "MathCompileError",
    "compile_distractor_value",
    "display_distractor",
    "display_sympy_value",
    "fraction_text",
    "parameter_combinations",
    "render_expr",
    "render_goal_display",
    "render_item_text",
    "render_matrix",
    "render_relation",
    "render_relations",
    "representative_item",
    "substitute_expr",
    "substitute_item",
]
