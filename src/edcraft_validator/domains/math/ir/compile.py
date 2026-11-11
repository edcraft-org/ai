"""Compile the closed math IR to SymPy.

No model-authored Python, ``eval`` or ``parse_expr`` is ever used. Unknown
operators, malformed trees and oversized inputs are rejected before SymPy sees
them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction

import sympy

from edcraft_validator.domains.math.ir.schema import (
    Expr,
    Given,
    Relation,
    SymbolSpec,
)

MAX_NODES = 200
MAX_DEPTH = 24
MAX_EXPONENT = 12

_UNARY = {
    "sqrt": sympy.sqrt,
    "abs": sympy.Abs,
    "exp": sympy.exp,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
}
_BINARY = {
    "sub": lambda a, b: a - b,
    "div": lambda a, b: a / b,
    "pow": lambda a, b: a**b,
}
_NARY = {
    "add": sympy.Add,
    "mul": sympy.Mul,
}


class MathCompileError(ValueError):
    """The IR is outside the supported closed expression subset."""


def parse_exact(value: str) -> Fraction:
    """Parse an exact decimal or rational literal; reject floats and infinities."""
    text = value.strip()
    if not text:
        raise MathCompileError("empty numeric literal")
    if text.lower() in {"nan", "inf", "+inf", "-inf", "infinity"}:
        raise MathCompileError("non-finite numeric literals are unsupported")
    try:
        result = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise MathCompileError(f"invalid numeric literal: {value!r}") from exc
    if result.denominator <= 0:
        raise MathCompileError("numeric literal has a non-positive denominator")
    return result


def rational(value: Fraction | int) -> sympy.Rational:
    if isinstance(value, int):
        return sympy.Integer(value)
    return sympy.Rational(value.numerator, value.denominator)


def build_symbols(
    symbols: list[SymbolSpec],
) -> dict[str, sympy.Symbol]:
    built: dict[str, sympy.Symbol] = {}
    for spec in symbols:
        # SymPy treats assumptions as tri-state facts. Passing ``False`` for a
        # narrow fact (positive/nonzero/integer) can contradict a broader one
        # such as ``real=True``, so only asserted facts are forwarded.
        assumptions: dict[str, bool] = {}
        if spec.domain == "real":
            assumptions["real"] = True
        if spec.domain == "integer" or spec.integer:
            assumptions["integer"] = True
        if spec.domain == "rational":
            assumptions["rational"] = True
        if spec.positive:
            assumptions["positive"] = True
        if spec.nonzero:
            assumptions["nonzero"] = True
        built[spec.name] = sympy.Symbol(spec.name, **assumptions)
    return built


def _check_tree(expr: Expr, depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        raise MathCompileError("expression nesting is too deep")
    if expr.op is None:
        return 1
    if expr.op == "pow" and len(expr.args) == 2:
        exponent = expr.args[1]
        if exponent.num is not None and abs(parse_exact(exponent.num)) > MAX_EXPONENT:
            raise MathCompileError("exponents are bounded")
    count = 1
    for child in expr.args:
        count += _check_tree(child, depth + 1)
        if count > MAX_NODES:
            raise MathCompileError("expression has too many nodes")
    return count


def compile_expr(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> sympy.Expr:
    _check_tree(expr)
    return _compile(expr, symbols, params or {})


def _compile(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> sympy.Expr:
    if expr.num is not None:
        value = parse_exact(expr.num)
        return rational(value)
    if expr.sym is not None:
        try:
            return symbols[expr.sym]
        except KeyError as exc:
            raise MathCompileError(f"unknown symbol {expr.sym!r}") from exc
    if expr.param is not None:
        try:
            return rational(params[expr.param])
        except KeyError as exc:
            raise MathCompileError(f"unbound parameter {expr.param!r}") from exc
    if expr.op is None:
        raise MathCompileError("expression node has no kind")
    if expr.op in _NARY:
        if not expr.args:
            raise MathCompileError(f"operator {expr.op!r} requires arguments")
        return _NARY[expr.op](
            *[_compile(child, symbols, params) for child in expr.args]
        )
    if expr.op in _BINARY:
        if len(expr.args) != 2:
            raise MathCompileError(f"operator {expr.op!r} requires two arguments")
        left, right = (_compile(child, symbols, params) for child in expr.args)
        return _BINARY[expr.op](left, right)
    if expr.op in _UNARY:
        if len(expr.args) != 1:
            raise MathCompileError(f"operator {expr.op!r} requires one argument")
        return _UNARY[expr.op](_compile(expr.args[0], symbols, params))
    if expr.op == "log":
        if len(expr.args) not in {1, 2}:
            raise MathCompileError("log requires one or two arguments")
        return sympy.log(*[_compile(child, symbols, params) for child in expr.args])
    raise MathCompileError(f"unsupported operator {expr.op!r}")


def compile_relation(
    relation: Relation,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> sympy.Rel:
    left = compile_expr(relation.lhs, symbols, params)
    right = compile_expr(relation.rhs, symbols, params)
    operators = {
        "eq": sympy.Eq,
        "ne": sympy.Ne,
        "lt": sympy.Lt,
        "le": sympy.Le,
        "gt": sympy.Gt,
        "ge": sympy.Ge,
    }
    return operators[relation.kind](left, right)


def compile_givens(
    givens: list[Given],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> list[sympy.Rel]:
    relations: list[sympy.Rel] = []
    for given in givens:
        if given.kind == "relation" and given.relation is not None:
            relations.append(compile_relation(given.relation, symbols, params))
    return relations


def exact_fraction(value: sympy.Expr) -> Fraction:
    """Convert an exact SymPy number to a Fraction; reject floats and symbols."""
    if not value.is_number:
        raise MathCompileError(f"expected an exact number, got {value!r}")
    rational_value = sympy.Rational(value)
    return Fraction(int(rational_value.p), int(rational_value.q))


def is_finite(value: sympy.Expr) -> bool:
    return bool(value.is_finite)


def bounded_int(value: sympy.Expr, *, limit: int = 10_000) -> int:
    if not value.is_Integer:
        raise MathCompileError("expected an integer")
    result = int(value)
    if abs(result) > limit:
        raise MathCompileError("integer result is out of bounds")
    return result


def finite_float(value: sympy.Expr) -> float:
    numeric = complex(sympy.N(value, 30))
    if not math.isfinite(numeric.real) or abs(numeric.imag) > 1e-18:
        raise MathCompileError("expected a finite real value")
    return numeric.real
