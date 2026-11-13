"""Compile declared answers and distractor values into SymPy objects.

Answer strings in the IR are *validator-authored* (topic code or a review
decision), never free model output. Model output is always the typed expression
tree. Parsing here is therefore bounded: a restricted global namespace, a length
limit and an explicit symbol table.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

import sympy
from sympy.parsing.sympy_parser import parse_expr

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
)
from edcraft_validator.domains.math.ir.schema import (
    Answer,
    AnswerRecipe,
    Expr,
    Interval,
    RecipeInterval,
    SymbolSpec,
)

MAX_ANSWER_TEXT = 400

_SAFE_NAMES = {
    "Integer": sympy.Integer,
    "Rational": sympy.Rational,
    "Float": sympy.Float,
    "Abs": sympy.Abs,
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "log": sympy.log,
    "ln": sympy.log,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "sinh": sympy.sinh,
    "cosh": sympy.cosh,
    "tanh": sympy.tanh,
    "factorial": sympy.factorial,
    "binomial": sympy.binomial,
    "pi": sympy.pi,
    "E": sympy.E,
    "I": sympy.I,
    "oo": sympy.oo,
    "zoo": sympy.zoo,
    "nan": sympy.nan,
    "true": sympy.true,
    "false": sympy.false,
    "True": sympy.true,
    "False": sympy.false,
}

_BOOLEAN_TEXT = {
    "true": sympy.true,
    "false": sympy.false,
    "True": sympy.true,
    "False": sympy.false,
}


def parse_answer_expr(
    text: str,
    symbols: dict[str, sympy.Symbol],
) -> sympy.Expr:
    """Parse one bounded answer fragment in an explicit symbol namespace."""
    stripped = text.strip()
    if not stripped:
        raise MathCompileError("answer text is empty")
    if len(stripped) > MAX_ANSWER_TEXT:
        raise MathCompileError("answer text is too long")
    try:
        return parse_expr(
            stripped,
            local_dict=dict(symbols),
            global_dict=dict(_SAFE_NAMES),
            evaluate=True,
        )
    except (SyntaxError, TypeError, ValueError, NameError) as exc:
        raise MathCompileError(f"invalid answer expression: {text!r}") from exc


def compile_answer(
    answer: Answer,
    symbol_specs: list[SymbolSpec],
) -> object:
    """Turn a declared answer into the SymPy object its primitive compares."""
    symbols = build_symbols(symbol_specs)
    if answer.kind == "numeric" or answer.kind == "expression":
        if len(answer.items) != 1:
            raise MathCompileError(f"{answer.kind} answers need exactly one item")
        return parse_answer_expr(answer.items[0], symbols)
    if answer.kind == "set":
        return sympy.FiniteSet(
            *[parse_answer_expr(item, symbols) for item in answer.items]
        )
    if answer.kind == "tuple":
        return sympy.Tuple(*[parse_answer_expr(item, symbols) for item in answer.items])
    if answer.kind == "interval":
        if answer.interval is None:
            raise MathCompileError("interval answers require an interval value")
        return compile_interval(answer.interval, symbols)
    if answer.kind == "matrix":
        if answer.matrix is None:
            raise MathCompileError("matrix answers require a matrix value")
        return sympy.Matrix(
            [
                [parse_answer_expr(cell, symbols) for cell in row]
                for row in answer.matrix
            ]
        )
    if answer.kind == "boolean":
        if answer.boolean is None:
            text = answer.items[0] if answer.items else "false"
            return _BOOLEAN_TEXT.get(text)
        return sympy.true if answer.boolean else sympy.false
    raise MathCompileError(f"unsupported answer kind {answer.kind!r}")


def compile_interval(
    interval: Interval,
    symbols: dict[str, sympy.Symbol],
) -> sympy.Interval:
    lower = (
        sympy.S.NegativeInfinity
        if interval.lower is None
        else parse_answer_expr(interval.lower, symbols)
    )
    upper = (
        sympy.S.Infinity
        if interval.upper is None
        else parse_answer_expr(interval.upper, symbols)
    )
    return sympy.Interval(
        lower,
        upper,
        left_open=interval.lower_open,
        right_open=interval.upper_open,
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

    if recipe.kind == "numeric" or recipe.kind == "expression":
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
