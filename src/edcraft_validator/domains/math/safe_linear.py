"""Exact, allowlisted evaluation of linear-equation expression recipes."""

from __future__ import annotations

import ast
import math
from fractions import Fraction
from typing import Final

from edcraft_validator.domains.math.math_types import (
    MATH_PARAMETER_NAMES,
    MATH_VARIABLE_NAME,
    MAX_EXPRESSION_LENGTH,
)

ALLOWED_EXPRESSION_NAMES: Final = frozenset({*MATH_PARAMETER_NAMES, MATH_VARIABLE_NAME})
MAX_EXPRESSION_NODES: Final = 100
MAX_CONSTANT_ABSOLUTE_VALUE: Final = 10_000
_BINARY_OPERATORS: Final = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
}


def evaluate_expression(expression: str, values: dict[str, int]) -> Fraction:
    """Evaluate one allowed expression with exact rational arithmetic."""
    node = _parse_expression(expression)
    return _evaluate(node, values)


def validate_expression(expression: str) -> None:
    """Reject expressions outside the small supported arithmetic subset."""
    _parse_expression(expression)


def format_fraction(value: Fraction) -> str:
    """Render an exact rational answer without floating-point rounding."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _parse_expression(expression: str) -> ast.AST:
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression must be a non-blank string")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expression exceeds {MAX_EXPRESSION_LENGTH} characters")
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError as exc:
        raise ValueError(f"invalid expression {expression!r}: {exc.msg}") from exc
    if sum(1 for _ in ast.walk(node)) > MAX_EXPRESSION_NODES:
        raise ValueError(f"expression exceeds {MAX_EXPRESSION_NODES} syntax nodes")
    _validate(node, depth=0)
    return node


def _validate(node: ast.AST, *, depth: int) -> None:
    if depth > 20:
        raise ValueError("expression is too deeply nested")
    if isinstance(node, ast.Constant):
        if type(node.value) is int:
            if abs(node.value) > MAX_CONSTANT_ABSOLUTE_VALUE:
                raise ValueError("expression integer constant is too large")
            return
        if type(node.value) is float and math.isfinite(node.value):
            if abs(node.value) > MAX_CONSTANT_ABSOLUTE_VALUE:
                raise ValueError("expression numeric constant is too large")
            return
        raise ValueError("expression supports only numeric constants")
    if isinstance(node, ast.Name):
        if node.id not in ALLOWED_EXPRESSION_NAMES:
            raise ValueError(f"expression uses unsupported name {node.id!r}")
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        _validate(node.left, depth=depth + 1)
        _validate(node.right, depth=depth + 1)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        _validate(node.operand, depth=depth + 1)
        return
    raise ValueError(f"unsupported expression syntax: {type(node).__name__}")


def _evaluate(node: ast.AST, values: dict[str, int]) -> Fraction:
    if isinstance(node, ast.Constant):
        if type(node.value) is int:
            return Fraction(node.value)
        return Fraction(str(node.value))
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(f"expression name {node.id!r} has no value")
        value = values[node.id]
        if type(value) is not int:
            raise ValueError(f"expression name {node.id!r} must be an integer")
        return Fraction(value)
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, values)
        right = _evaluate(node.right, values)
        try:
            return _BINARY_OPERATORS[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise ValueError("expression divides by zero") from exc
    if isinstance(node, ast.UnaryOp):
        return -_evaluate(node.operand, values)
    raise AssertionError(f"unvalidated expression node: {type(node).__name__}")
