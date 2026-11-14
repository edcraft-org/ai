"""Compile structured answer recipes into the SymPy objects graders compare.

Recipes are typed expression trees, never text: there is no parser and no
``parse_expr`` on model output anywhere in this module. The deterministic engine
grades the compiled value; the form registry inspects its shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

import sympy

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
)
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Expr,
    RecipeInterval,
    SymbolSpec,
)


def compile_answer_recipe(
    recipe: AnswerRecipe,
    symbol_specs: list[SymbolSpec],
    params: Mapping[str, Fraction] | None = None,
) -> object:
    """Compile a structured answer recipe into the SymPy object graders compare."""
    symbols = build_symbols(symbol_specs)
    try:
        return _compile_recipe(recipe, symbols, params or {})
    except MathCompileError as exc:
        raise MathCompileError(f"invalid {recipe.kind} answer recipe: {exc}") from exc


def _compile_recipe(
    recipe: AnswerRecipe,
    symbols: dict[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> object:
    def compile_item(expr: Expr) -> sympy.Expr:
        return compile_expr(expr, symbols, params)

    if recipe.kind in {"numeric", "expression"}:
        if len(recipe.items) != 1:
            raise MathCompileError(
                f"{recipe.kind} answer recipes need exactly one item"
            )
        return compile_item(recipe.items[0])
    if recipe.kind == "set":
        return sympy.FiniteSet(*[compile_item(item) for item in recipe.items])
    if recipe.kind == "tuple":
        return sympy.Tuple(*[compile_item(item) for item in recipe.items])
    if recipe.kind == "matrix":
        if recipe.matrix is None:
            raise MathCompileError("matrix answer recipes need a matrix value")
        return sympy.Matrix(
            [[compile_item(cell) for cell in row] for row in recipe.matrix]
        )
    if recipe.kind == "interval":
        if recipe.interval is None:
            raise MathCompileError("interval answer recipes need an interval value")
        return _compile_recipe_interval(recipe.interval, symbols, params)
    if recipe.kind == "boolean":
        if recipe.boolean is None:
            raise MathCompileError("boolean answer recipes need a boolean value")
        return sympy.true if recipe.boolean else sympy.false
    raise MathCompileError(f"unsupported answer recipe kind {recipe.kind!r}")


def _compile_recipe_interval(
    interval: RecipeInterval,
    symbols: dict[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> sympy.Interval:
    lower = (
        sympy.S.NegativeInfinity
        if interval.lower is None
        else compile_expr(interval.lower, symbols, params)
    )
    upper = (
        sympy.S.Infinity
        if interval.upper is None
        else compile_expr(interval.upper, symbols, params)
    )
    return sympy.Interval(
        lower,
        upper,
        left_open=interval.lower_open,
        right_open=interval.upper_open,
    )
