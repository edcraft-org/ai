"""Answer-type primitives: numeric, expression, solution set, and options.

Every primitive is tri-state. A counterexample is a hard failure; an exhausted
heuristic is ``inconclusive`` and routes to review. No primitive claims more
than it can establish.
"""

from __future__ import annotations

import math
import random
from fractions import Fraction
from typing import Any

import sympy

from edcraft_validator.domains.math.ir.schema import Interval, PrimitiveSpec
from edcraft_validator.domains.math.validation.results import PrimitiveResult

_NUMERIC_TOLERANCE = 1e-12


def _result(
    primitive: str, status: str, reason: str = "", **evidence: Any
) -> PrimitiveResult:
    return PrimitiveResult(
        primitive=primitive,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        evidence=evidence,
    )


def expression_equiv(
    expected: sympy.Expr,
    actual: sympy.Expr,
    *,
    symbols: list[sympy.Symbol] | None = None,
    samples: int = 12,
) -> PrimitiveResult:
    """Compare two expressions. Only a numeric counterexample proves inequality."""
    difference = sympy.simplify(sympy.together(expected - actual))
    if difference == 0:
        return _result("expression_equiv", "passed", "expressions simplify equal")
    if not difference.free_symbols:
        value = _real_number(difference)
        if value is not None and abs(value) <= _NUMERIC_TOLERANCE:
            return _result("expression_equiv", "passed", "constant difference is zero")
        return _result(
            "expression_equiv",
            "failed",
            "constant difference is non-zero",
            difference=sympy.sstr(difference),
        )
    equality = getattr(difference, "equals", None)
    if callable(equality):
        try:
            decided = equality(0)
        except (TypeError, ValueError):
            decided = None
        if decided is True:
            return _result("expression_equiv", "passed", "equals(0) accepted")
    names = symbols or sorted(difference.free_symbols, key=sympy.default_sort_key)
    counterexample = _find_counterexample(difference, names, samples)
    if counterexample is not None:
        return _result(
            "expression_equiv",
            "failed",
            "a numeric counterexample disproves equivalence",
            counterexample={str(k): sympy.sstr(v) for k, v in counterexample.items()},
        )
    return _result(
        "expression_equiv",
        "inconclusive",
        "simplification and numeric sampling did not decide equivalence",
    )


def numeric_equal(
    expected: Any,
    actual: Any,
    *,
    rel_tol: float = 0.0,
    abs_tol: float = 0.0,
) -> PrimitiveResult:
    try:
        left = _as_fraction(expected)
        right = _as_fraction(actual)
    except (TypeError, ValueError, ZeroDivisionError):
        return _result("numeric", "failed", "values are not finite numbers")
    if left == right:
        return _result("numeric", "passed", "exact values are equal")
    if rel_tol == 0.0 and abs_tol == 0.0:
        return _result(
            "numeric",
            "failed",
            "exact values differ",
            expected=str(left),
            actual=str(right),
        )
    left_float, right_float = float(left), float(right)
    difference = abs(left_float - right_float)
    allowed = max(abs_tol, rel_tol * max(abs(left_float), abs(right_float)))
    if difference <= allowed:
        return _result("numeric", "passed", "difference is within tolerance")
    return _result(
        "numeric",
        "failed",
        "difference exceeds tolerance",
        difference=difference,
        allowed=allowed,
    )


def solution_set_equal(
    expected: sympy.Set,
    actual: sympy.Set,
    *,
    symbols: list[sympy.Symbol] | None = None,
) -> PrimitiveResult:
    # A single candidate answer often arrives as a bare scalar while the derived
    # key is a finite set. Treat the scalar as a one-element set instead of
    # reporting a spurious type mismatch.
    if isinstance(expected, sympy.Set) and not isinstance(actual, sympy.Set):
        actual = sympy.FiniteSet(actual)
    elif isinstance(actual, sympy.Set) and not isinstance(expected, sympy.Set):
        expected = sympy.FiniteSet(expected)
    if expected == actual:
        return _result("solution_set", "passed", "solution sets are identical")
    if expected is sympy.EmptySet or actual is sympy.EmptySet:
        return _result(
            "solution_set",
            "failed",
            "one solution set is empty and the other is not",
            expected=sympy.sstr(expected),
            actual=sympy.sstr(actual),
        )
    if isinstance(expected, sympy.FiniteSet) and isinstance(actual, sympy.FiniteSet):
        left = list(expected.args)
        right = list(actual.args)
        if len(left) != len(right):
            return _result(
                "solution_set",
                "failed",
                "solution sets have different cardinality",
                expected=sympy.sstr(expected),
                actual=sympy.sstr(actual),
            )
        unmatched = list(right)
        for candidate in left:
            for index, other in enumerate(unmatched):
                if (
                    expression_equiv(candidate, other, symbols=symbols).status
                    == "passed"
                ):
                    unmatched.pop(index)
                    break
            else:
                return _result(
                    "solution_set",
                    "failed",
                    "solution sets contain different elements",
                    expected=sympy.sstr(expected),
                    actual=sympy.sstr(actual),
                )
        return _result("solution_set", "passed", "finite solution sets match")
    if isinstance(expected, sympy.Interval) and isinstance(actual, sympy.Interval):
        return interval_equal(
            Interval(
                lower=None
                if expected.start is sympy.S.NegativeInfinity
                else sympy.sstr(expected.start),
                upper=None
                if expected.end is sympy.S.Infinity
                else sympy.sstr(expected.end),
                lower_open=bool(expected.left_open),
                upper_open=bool(expected.right_open),
            ),
            Interval(
                lower=None
                if actual.start is sympy.S.NegativeInfinity
                else sympy.sstr(actual.start),
                upper=None
                if actual.end is sympy.S.Infinity
                else sympy.sstr(actual.end),
                lower_open=bool(actual.left_open),
                upper_open=bool(actual.right_open),
            ),
        )
    return _result(
        "solution_set",
        "inconclusive",
        "solution sets are not both finite or both intervals",
        expected=sympy.sstr(expected),
        actual=sympy.sstr(actual),
    )


def collection_equal(
    expected: list[Any],
    actual: list[Any],
    *,
    ordered: bool = False,
    multiplicity: bool = True,
    symbols: list[sympy.Symbol] | None = None,
) -> PrimitiveResult:
    left = list(expected)
    right = list(actual)
    if not multiplicity:
        left = _unique(left)
        right = _unique(right)
    if len(left) != len(right):
        return _result(
            "collection",
            "failed",
            "collections have different lengths",
            expected=[sympy.sstr(item) for item in left],
            actual=[sympy.sstr(item) for item in right],
        )
    if ordered:
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            if expression_equiv(a, b, symbols=symbols).status != "passed":
                return _result(
                    "collection",
                    "failed",
                    f"ordered element {index} differs",
                )
        return _result("collection", "passed", "ordered collections match")
    unmatched = list(right)
    for item in left:
        for index, other in enumerate(unmatched):
            if expression_equiv(item, other, symbols=symbols).status == "passed":
                unmatched.pop(index)
                break
        else:
            return _result(
                "collection",
                "failed",
                "collections contain different elements",
            )
    return _result("collection", "passed", "collections match as multisets")


def interval_equal(expected: Interval, actual: Interval) -> PrimitiveResult:
    if (
        expected.lower == actual.lower
        and expected.upper == actual.upper
        and expected.lower_open == actual.lower_open
        and expected.upper_open == actual.upper_open
    ):
        return _result("interval", "passed", "intervals match")
    return _result(
        "interval",
        "failed",
        "interval endpoints or openness differ",
        expected=expected.model_dump(mode="json"),
        actual=actual.model_dump(mode="json"),
    )


def matrix_equal(expected: list[list[Any]], actual: list[list[Any]]) -> PrimitiveResult:
    if len(expected) != len(actual) or any(
        len(row) != len(other) for row, other in zip(expected, actual, strict=False)
    ):
        return _result("matrix_vector", "failed", "matrix shapes differ")
    for row_index, (row, other) in enumerate(zip(expected, actual, strict=True)):
        for column_index, (left, right) in enumerate(zip(row, other, strict=True)):
            if expression_equiv(left, right).status != "passed":
                return _result(
                    "matrix_vector",
                    "failed",
                    f"matrix entry {row_index},{column_index} differs",
                )
    return _result("matrix_vector", "passed", "matrices match entrywise")


def string_equal(
    expected: str, actual: str, *, mode: str = "normalised"
) -> PrimitiveResult:
    if mode == "exact":
        passed = expected == actual
    elif mode == "regex":
        import re

        passed = re.fullmatch(expected, actual) is not None
    elif mode == "levenshtein":
        passed = _levenshtein(expected, actual) <= 1
    else:
        passed = (
            " ".join(expected.split()).casefold() == " ".join(actual.split()).casefold()
        )
    if passed:
        return _result("string_choice", "passed", "strings match")
    return _result(
        "string_choice",
        "failed",
        "strings differ",
        expected=expected,
        actual=actual,
    )


def quantity_equal(
    expected: tuple[Any, str | None],
    actual: tuple[Any, str | None],
    *,
    unit_policy: str = "required",
) -> PrimitiveResult:
    expected_value, expected_unit = expected
    actual_value, actual_unit = actual
    if unit_policy != "ignore" and expected_unit != actual_unit:
        return _result(
            "quantity",
            "failed",
            "units differ",
            expected_unit=expected_unit,
            actual_unit=actual_unit,
        )
    numeric = numeric_equal(expected_value, actual_value)
    if numeric.status != "passed":
        return numeric.model_copy(update={"primitive": "quantity"})
    return _result("quantity", "passed", "value and unit match")


def check_primitive(
    primitive: PrimitiveSpec,
    *,
    expected: Any,
    actual: Any,
    symbols: list[sympy.Symbol] | None = None,
) -> PrimitiveResult:
    kind = primitive.type
    params = primitive.params
    if kind == "numeric":
        return numeric_equal(
            expected,
            actual,
            rel_tol=float(params.get("rel_tol", 0.0)),
            abs_tol=float(params.get("abs_tol", 0.0)),
        )
    if kind == "expression_equiv":
        return expression_equiv(expected, actual, symbols=symbols)
    if kind == "solution_set":
        return solution_set_equal(expected, actual, symbols=symbols)
    if kind == "collection":
        return collection_equal(
            expected,
            actual,
            ordered=bool(params.get("ordered", False)),
            multiplicity=bool(params.get("multiplicity", True)),
            symbols=symbols,
        )
    if kind == "interval":
        return interval_equal(expected, actual)
    if kind == "matrix_vector":
        return matrix_equal(expected, actual)
    if kind == "string_choice":
        return string_equal(
            str(expected), str(actual), mode=str(params.get("mode", "normalised"))
        )
    if kind == "quantity":
        return quantity_equal(
            expected,
            actual,
            unit_policy=str(params.get("unit_policy", "required")),
        )
    if kind == "proof":
        return _result(
            "proof",
            "inconclusive",
            "proof checking is not enabled; route to the proof track or human review",
        )
    return _result(kind, "inconclusive", f"unknown primitive {kind!r}")


def _as_fraction(value: Any) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, sympy.Rational):
        return Fraction(int(value.p), int(value.q))
    if isinstance(value, sympy.Integer):
        return Fraction(int(value))
    if isinstance(value, (float, str)):
        return Fraction(value)
    raise TypeError(f"not a finite number: {type(value).__name__}")


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
    samples: int,
) -> dict[sympy.Symbol, sympy.Expr] | None:
    if not symbols:
        return None
    rng = random.Random(20261112)
    denominator = sympy.denom(sympy.together(expression))
    for _ in range(samples):
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
        if value is None:
            continue
        if abs(value) > 1e-10:
            return point
    return None


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if all(expression_equiv(value, other).status != "passed" for other in result):
            result.append(value)
    return result


def _levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, start=1):
        current = [i]
        for j, char_right in enumerate(right, start=1):
            insert = previous[j] + 1
            delete = current[j - 1] + 1
            substitute = previous[j - 1] + (char_left != char_right)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]
