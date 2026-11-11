"""Exact arithmetic and allowlist tests for math expressions."""

from fractions import Fraction

import pytest

from edcraft_validator.domains.math.safe_linear import (
    evaluate_expression,
    format_fraction,
    validate_expression,
)


@pytest.mark.parametrize(
    ("expression", "values", "expected"),
    [
        ("(c - b) / a", {"a": 2, "b": 2, "c": 5}, Fraction(3, 2)),
        ("(c - b) / a", {"a": 3, "b": 2, "c": 5}, Fraction(1)),
        ("(b - c) / a", {"a": 2, "b": 1, "c": 4}, Fraction(-3, 2)),
        ("-a * (b + c)", {"a": 2, "b": 3, "c": 4}, Fraction(-14)),
        ("a / 2", {"a": 5}, Fraction(5, 2)),
        ("x + a", {"x": 10, "a": 2}, Fraction(12)),
    ],
)
def test_exact_evaluation(expression, values, expected) -> None:
    assert evaluate_expression(expression, values) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(5), "5"),
        (Fraction(-5), "-5"),
        (Fraction(1, 2), "1/2"),
        (Fraction(-3, 2), "-3/2"),
        (Fraction(6, 4), "3/2"),
    ],
)
def test_fraction_formatting(value, expected) -> None:
    assert format_fraction(value) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "a ** 2",
        "a // 2",
        "a % 2",
        "abs(a)",
        "d + 1",
        "a.real",
        "a if b else c",
        "'text'",
        "a +",
        "",
    ],
)
def test_unsupported_expressions_are_rejected(expression) -> None:
    with pytest.raises(ValueError):
        validate_expression(expression)


def test_division_by_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="divides by zero"):
        evaluate_expression("a / b", {"a": 1, "b": 0})


def test_missing_name_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="has no value"):
        evaluate_expression("a + x", {"a": 1})
