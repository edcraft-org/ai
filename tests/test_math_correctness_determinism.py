"""The same request gives byte-identical JSON apart from its duration."""

from __future__ import annotations

import json

import pytest

from edcraft_validator.application.math_correctness import check_math_correctness


def _num(value: int | str) -> dict[str, str]:
    return {"num": str(value)}


def _symbol(name: str) -> dict[str, str]:
    return {"sym": name}


def _op(name: str, *args: dict[str, object]) -> dict[str, object]:
    return {"op": name, "args": list(args)}


X = _symbol("x")

REQUESTS = {
    "evaluate-with-witness": {
        "problem": {
            "operation": "evaluate",
            "symbols": [{"name": "x"}, {"name": "y"}],
            "expression": _op("mul", _symbol("x"), _symbol("y")),
        },
        "answer": {"expression": _op("mul", _num(2), X)},
    },
    "simplify": {
        "problem": {
            "operation": "simplify",
            "symbols": [{"name": "x"}],
            "expression": _op("div", X, X),
        },
        "answer": {"expression": _num(1)},
    },
    "solve": {
        "problem": {
            "operation": "solve",
            "symbols": [{"name": "x"}],
            "solve_for": ["x"],
            "relations": [{"lhs": _op("pow", X, _num(2)), "rhs": _num(4)}],
        },
        "answer": {"kind": "set", "items": [_num(-2), _num(2)]},
    },
    "differentiate": {
        "problem": {
            "operation": "differentiate",
            "symbols": [{"name": "x"}],
            "variable": "x",
            "expression": _op("pow", X, _num(3)),
        },
        "answer": {"expression": _op("mul", _num(3), _op("pow", X, _num(2)))},
    },
    "determinant": {
        "problem": {
            "operation": "determinant",
            "matrix": [[_num(1), _num(2)], [_num(3), _num(4)]],
        },
        "answer": {"expression": _num(-2)},
    },
    "lu": {
        "problem": {
            "operation": "lu",
            "matrix": [[_num(2), _num(1)], [_num(4), _num(3)]],
        },
        "answer": {
            "kind": "lu",
            "permutation": [[_num(1), _num(0)], [_num(0), _num(1)]],
            "lower": [[_num(1), _num(0)], [_num(2), _num(1)]],
            "upper": [[_num(2), _num(1)], [_num(0), _num(1)]],
        },
    },
}


@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_repeated_requests_are_identical_except_duration(name: str):
    request = REQUESTS[name]
    first = check_math_correctness(request).model_dump(mode="json")
    second = check_math_correctness(request).model_dump(mode="json")

    assert first.pop("duration_ms") >= 0
    assert second.pop("duration_ms") >= 0
    assert first == second
    # Compare insertion order too: hash-randomised set iteration must not leak.
    assert json.dumps(first) == json.dumps(second)
