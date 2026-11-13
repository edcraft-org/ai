"""Any additive constant is accepted for an antiderivative."""

from __future__ import annotations

import pytest

from edcraft_validator.application.math_correctness import check_math_correctness


def _num(value: int) -> dict[str, str]:
    return {"num": str(value)}


def _symbol(name: str) -> dict[str, str]:
    return {"sym": name}


def _op(name: str, *args: dict[str, object]) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def _antiderivative(answer: dict[str, object]):
    return check_math_correctness(
        {
            "problem": {
                "operation": "antiderivative",
                "symbols": [{"name": "x"}],
                "variable": "x",
                "expression": _op("div", _num(1), _symbol("x")),
            },
            "answer": {"expression": answer},
        }
    )


def _primitive(constant: int | None = None) -> dict[str, object]:
    primitive = _op("log", _op("abs", _symbol("x")))
    if constant is None:
        return primitive
    return _op("add", primitive, _num(constant))


@pytest.mark.parametrize("constant", [None, 0, 5, -7])
def test_any_additive_constant_is_accepted(constant: int | None):
    result = _antiderivative(_primitive(constant))
    assert result.outcome == "correct", result.reason


def test_a_different_function_is_not_accepted():
    # ln|x| alone is a primitive of 1/x; ln|x| + x is not.
    result = _antiderivative(_op("add", _primitive(), _symbol("x")))
    assert result.outcome == "incorrect", result.reason
