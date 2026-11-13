"""Focused regressions for scalar real-domain sign inference.

These tests pin the branch that decides whether a rational power is positive on
the problem's real domain.  A principal even root is real only for a positive
base, so a *nonzero* base is not enough: ``sqrt(-2)`` is imaginary.
"""

from __future__ import annotations

import sympy

from edcraft_validator.domains.math.engine.conditions import Condition
from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    MathAnswer,
    MathProblem,
)
from edcraft_validator.domains.math.engine.scalar import check_scalar
from edcraft_validator.domains.math.engine.scalar_domains import (
    _expr_sign,
    condition_implied,
)
from edcraft_validator.domains.math.ir.schema import Expr, SymbolSpec

A, B = sympy.symbols("a b", real=True)


def num(value: object) -> Expr:
    return Expr(num=str(value))


def sym(name: str) -> Expr:
    return Expr(sym=name)


def mul(*args: Expr) -> Expr:
    return Expr(op="mul", args=list(args))


def sqrt(value: Expr) -> Expr:
    return Expr(op="sqrt", args=[value])


def _context(*symbols: SymbolSpec) -> EngineContext:
    request = CorrectnessRequest(
        problem=MathProblem(
            operation="simplify", expression=num(1), symbols=list(symbols)
        ),
        answer=MathAnswer(kind="expression", expression=num(2)),
    )
    return EngineContext.create(request)


def _outcome(expression: Expr, answer: Expr, symbols: list[SymbolSpec]) -> str:
    request = CorrectnessRequest(
        problem=MathProblem(
            operation="simplify", expression=expression, symbols=symbols
        ),
        answer=MathAnswer(kind="expression", expression=answer),
    )
    return check_scalar(EngineContext.create(request)).outcome


def test_even_root_sign_requires_a_positive_base() -> None:
    """``a*b > 0`` proves ``a`` nonzero, not positive, so ``sqrt(a)`` has no sign.

    At ``a = b = -2`` the source guard holds while ``sqrt(a)`` is imaginary, so
    claiming ``sqrt(a) > 0`` (and, transitively, accepting the product identity)
    would be unsound.
    """
    ctx = _context(SymbolSpec(name="a"), SymbolSpec(name="b"))
    conditions = (Condition("gt", A * B),)

    assert condition_implied(conditions, Condition("gt", A), ctx) is not True
    assert condition_implied(conditions, Condition("gt", sympy.sqrt(A)), ctx) is None
    assert _expr_sign(conditions, sympy.sqrt(A)) is None
    assert _expr_sign(conditions, sympy.sqrt(A) * sympy.sqrt(B)) is None


def test_even_root_sign_rejects_nonzero_and_negative_bases() -> None:
    ctx = _context(SymbolSpec(name="a"))
    asserted = Condition("gt", sympy.sqrt(A))

    assert condition_implied((Condition("ne", A),), asserted, ctx) is None
    assert condition_implied((Condition("lt", A),), asserted, ctx) is None
    assert _expr_sign((Condition("ne", A),), sympy.sqrt(A)) is None
    assert _expr_sign((Condition("lt", A),), sympy.sqrt(A)) is None


def test_even_and_odd_root_signs_with_a_positive_base() -> None:
    ctx = _context(SymbolSpec(name="a"))
    conditions = (Condition("gt", A),)

    assert condition_implied(conditions, Condition("gt", sympy.sqrt(A)), ctx) is True
    assert _expr_sign(conditions, sympy.sqrt(A)) == 1

    # An odd denominator is a real cube (or higher odd) root, so the strict
    # positive base keeps the strict sign path it already had.
    cube_root = A ** sympy.Rational(1, 3)
    assert condition_implied(conditions, Condition("gt", cube_root), ctx) is True
    assert _expr_sign(conditions, cube_root) == 1


def test_sqrt_product_identity_needs_individual_signs() -> None:
    """Only ``a*b > 0`` is known: ``sqrt(a)*sqrt(b) = sqrt(a*b)`` is unsound.

    The public contract has no product-assumption channel, so the closest
    encoding is the source ``sqrt(a*b)`` whose only guard is ``a*b >= 0``.
    Even the strict ``a*b > 0`` used above admits ``a = b = -2``; there the
    candidate is not real, so it must not be accepted as ``correct``.
    """
    symbols = [SymbolSpec(name="a"), SymbolSpec(name="b")]
    assert (
        _outcome(
            sqrt(mul(sym("a"), sym("b"))),
            mul(sqrt(sym("a")), sqrt(sym("b"))),
            symbols,
        )
        == "incorrect"
    )


def test_sqrt_product_identity_with_positive_factors() -> None:
    symbols = [
        SymbolSpec(name="a", positive=True),
        SymbolSpec(name="b", positive=True),
    ]
    assert (
        _outcome(
            mul(sqrt(sym("a")), sqrt(sym("b"))),
            sqrt(mul(sym("a"), sym("b"))),
            symbols,
        )
        == "correct"
    )


def test_sqrt_product_identity_on_nonnegative_source_domain() -> None:
    """The two square roots themselves supply non-strict ``ge`` guards.

    This exercises the sign-category and boundary machinery for a product of
    non-strictly nonnegative factors, which a strict-only inference would leave
    ``unknown``.
    """
    symbols = [SymbolSpec(name="a"), SymbolSpec(name="b")]
    assert (
        _outcome(
            mul(sqrt(sym("a")), sqrt(sym("b"))),
            sqrt(mul(sym("a"), sym("b"))),
            symbols,
        )
        == "correct"
    )
