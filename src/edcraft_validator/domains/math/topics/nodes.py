"""Small constructors for the closed expression tree."""

from __future__ import annotations

from edcraft_validator.domains.math.ir.schema import Expr


def num(value: int | str) -> Expr:
    """An exact numeric literal. Integers are rendered without a decimal point."""
    return Expr(num=str(value))


def sym(name: str) -> Expr:
    """A declared symbol reference."""
    return Expr(sym=name)


def add(*args: Expr) -> Expr:
    """An n-ary sum."""
    return Expr(op="add", args=list(args))


def mul(*args: Expr) -> Expr:
    """An n-ary product."""
    return Expr(op="mul", args=list(args))


def sub(left: Expr, right: Expr) -> Expr:
    """A binary difference."""
    return Expr(op="sub", args=[left, right])


def div(left: Expr, right: Expr) -> Expr:
    """A binary quotient."""
    return Expr(op="div", args=[left, right])


def power(base: Expr, exponent: Expr) -> Expr:
    """A binary power. Named ``power`` to avoid shadowing the builtin."""
    return Expr(op="pow", args=[base, exponent])
