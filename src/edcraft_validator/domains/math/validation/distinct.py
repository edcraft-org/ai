"""Decide whether two compiled option values are the same answer.

This is a distinctness check, not a correctness oracle. Correctness belongs to
the deterministic engine; form belongs to ``validation/forms.py``. Here the only
question is whether two options would present the same value, which is a defect
in the question rather than a verdict on it.

``expression_equivalence`` keeps the tri-state discipline the fidelity check
needs: a numeric counterexample disproves equality, an exhausted heuristic is
``None``.
"""

from __future__ import annotations

import math
import random
from typing import Any

import sympy
from sympy.matrices.matrixbase import MatrixBase

_NUMERIC_TOLERANCE = 1e-12
_COUNTEREXAMPLE_SAMPLES = 12
_COUNTEREXAMPLE_SEED = 20261112


def same_value(left: Any, right: Any) -> bool:
    """Whether two compiled values are the same answer."""
    if isinstance(left, sympy.Tuple) or isinstance(right, sympy.Tuple):
        if not (isinstance(left, sympy.Tuple) and isinstance(right, sympy.Tuple)):
            return False
        if len(left) != len(right):
            return False
        return all(
            same_value(item_left, item_right)
            for item_left, item_right in zip(left, right, strict=True)
        )

    left_rows = _matrix_rows(left)
    right_rows = _matrix_rows(right)
    if left_rows is not None or right_rows is not None:
        if left_rows is None or right_rows is None:
            return False
        if len(left_rows) != len(right_rows):
            return False
        return all(
            len(left_row) == len(right_row)
            and all(
                same_value(cell_left, cell_right)
                for cell_left, cell_right in zip(left_row, right_row, strict=True)
            )
            for left_row, right_row in zip(left_rows, right_rows, strict=True)
        )

    if isinstance(left, sympy.Set) or isinstance(right, sympy.Set):
        if not (isinstance(left, sympy.Set) and isinstance(right, sympy.Set)):
            return False
        try:
            return bool(left == right)
        except (TypeError, ValueError):
            return False

    if isinstance(left, sympy.Expr) and isinstance(right, sympy.Expr):
        return expression_equivalence(left, right) is True

    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def expression_equivalence(
    left: sympy.Expr,
    right: sympy.Expr,
) -> bool | None:
    """Decide semantic equality; ``None`` means the comparison could not decide."""
    if left == right:
        return True
    difference = left - right
    # A sampled nonzero point already disproves equality, so try it before the
    # expensive symbolic simplification. Wrong choices are the common case and
    # should be rejected cheaply.
    names = sorted(difference.free_symbols, key=sympy.default_sort_key)
    if names and _find_counterexample(difference, names) is not None:
        return False
    try:
        difference = sympy.simplify(sympy.together(difference))
    except Exception:  # total: an undecidable difference stays undecided
        return None
    if difference == 0:
        return True
    if not difference.free_symbols:
        value = _real_number(difference)
        if value is None:
            return None
        return abs(value) <= _NUMERIC_TOLERANCE
    equality = getattr(difference, "equals", None)
    if callable(equality):
        try:
            decided = equality(0)
        except (TypeError, ValueError):
            decided = None
        if decided is True:
            return True
    return None


def _matrix_rows(value: Any) -> list[list[Any]] | None:
    if isinstance(value, MatrixBase):
        return value.tolist()
    if isinstance(value, list) and all(isinstance(row, list) for row in value):
        return value
    return None


def _real_number(value: sympy.Expr) -> float | None:
    try:
        numeric = complex(sympy.N(value, 30))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric.real) or abs(numeric.imag) > 1e-18:
        return None
    return numeric.real


def _find_counterexample(
    expression: sympy.Expr,
    symbols: list[sympy.Symbol],
) -> dict[sympy.Symbol, sympy.Expr] | None:
    """Sample bounded rational points until one disproves equality."""
    if not symbols:
        return None
    rng = random.Random(_COUNTEREXAMPLE_SEED)
    denominator = sympy.denom(sympy.together(expression))
    for _ in range(_COUNTEREXAMPLE_SAMPLES):
        point = {
            symbol: sympy.Rational(rng.randint(-5, 5), rng.randint(1, 5))
            for symbol in symbols
        }
        try:
            if sympy.simplify(denominator.subs(point)) == 0:
                continue
            value = _real_number(expression.subs(point))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if value is not None and abs(value) > 1e-10:
            return point
    return None
