"""Reproducible deterministic correctness examples and sampled qualification.

Run with the project environment. Each concrete example crosses the public
process boundary; expected outcomes below are explicit mathematical fixtures.
"""

from __future__ import annotations

import json

from edcraft_validator.application.math_correctness import check_math_correctness
from edcraft_validator.application.math_correctness_sampling import (
    qualify_math_template,
)
from edcraft_validator.domains.math.engine.sampling import SamplingSettings


def number(value: object) -> dict:
    return {"num": str(value)}


def expression(name: str, *args: dict) -> dict:
    return {"op": name, "args": list(args)}


def examples() -> list[tuple[str, dict, str]]:
    x = {"sym": "x"}

    def power(a: dict, b: int) -> dict:
        return expression("pow", a, number(b))

    source = power(x, 8)
    derivative = expression("mul", number(8), power(x, 7))
    symbols = [{"name": "x"}]
    polynomial = expression("sub", power(x, 2), number(1))
    matrix = [[number(i + 1 if i == j else 0) for j in range(4)] for i in range(4)]
    inverse = [
        [number(f"1/{i + 1}" if i == j else 0) for j in range(4)] for i in range(4)
    ]
    rows = [
        (
            "Differentiate x^8",
            {
                "operation": "differentiate",
                "variable": "x",
                "symbols": symbols,
                "expression": source,
            },
            {"expression": derivative},
            "correct",
        ),
        (
            "Reject incorrect derivative 9*x^7",
            {
                "operation": "differentiate",
                "variable": "x",
                "symbols": symbols,
                "expression": source,
            },
            {"expression": expression("mul", number(9), power(x, 7))},
            "incorrect",
        ),
        (
            "sqrt(x^2) = abs(x) on the reals",
            {
                "operation": "simplify",
                "symbols": symbols,
                "expression": expression("sqrt", power(x, 2)),
            },
            {"expression": expression("abs", x)},
            "correct",
        ),
        (
            "Mathematical equality without factor-form assessment",
            {"operation": "factor", "symbols": symbols, "expression": polynomial},
            {"expression": polynomial},
            "correct",
        ),
        (
            "Exact comparison rejects a tiny nonzero difference",
            {"operation": "evaluate", "expression": number(0)},
            {"expression": number("1/10000000000000")},
            "incorrect",
        ),
        (
            "Antiderivative of exp(2*x)",
            {
                "operation": "antiderivative",
                "variable": "x",
                "symbols": symbols,
                "expression": expression("exp", expression("mul", number(2), x)),
            },
            {
                "expression": expression(
                    "div", expression("exp", expression("mul", number(2), x)), number(2)
                )
            },
            "correct",
        ),
        (
            "Integrate sin(x) from 0 to pi",
            {
                "operation": "definite-integral",
                "variable": "x",
                "symbols": symbols,
                "expression": expression("sin", x),
                "lower": number(0),
                "upper": expression("acos", number(-1)),
            },
            {"expression": number(2)},
            "correct",
        ),
        (
            "Solve x^4 - 5*x^2 + 4 = 0",
            {
                "operation": "solve",
                "symbols": symbols,
                "solve_for": ["x"],
                "relations": [
                    {
                        "lhs": expression(
                            "add",
                            power(x, 4),
                            expression("mul", number(-5), power(x, 2)),
                            number(4),
                        ),
                        "rhs": number(0),
                    }
                ],
            },
            {"kind": "set", "items": [number(i) for i in [-2, -1, 1, 2]]},
            "correct",
        ),
        (
            "Solve (x-1)/(x+2) <= 0",
            {
                "operation": "solve",
                "symbols": symbols,
                "solve_for": ["x"],
                "relations": [
                    {
                        "kind": "le",
                        "lhs": expression(
                            "div",
                            expression("sub", x, number(1)),
                            expression("add", x, number(2)),
                        ),
                        "rhs": number(0),
                    }
                ],
            },
            {
                "kind": "set",
                "intervals": [
                    {
                        "lower": number(-2),
                        "upper": number(1),
                        "lower_open": True,
                        "upper_open": False,
                    }
                ],
            },
            "correct",
        ),
        (
            "4x4 determinant",
            {"operation": "determinant", "matrix": matrix},
            {"expression": number(24)},
            "correct",
        ),
        (
            "4x4 inverse",
            {"operation": "inverse", "matrix": matrix},
            {"kind": "matrix", "matrix": inverse},
            "correct",
        ),
    ]
    return [
        (title, {"problem": problem, "answer": answer}, expected)
        for title, problem, answer, expected in rows
    ]


def run() -> dict:
    results = []
    for title, request, expected in examples():
        observed = check_math_correctness(request)
        results.append(
            {
                "example": title,
                "expected": expected,
                "matches": observed.outcome == expected,
                "request": request,
                "result": observed.model_dump(mode="json"),
            }
        )
    template = {
        "request": {
            "problem": {
                "operation": "differentiate",
                "symbols": [{"name": "x"}],
                "variable": "x",
                "expression": expression(
                    "mul", {"param": "a"}, expression("pow", {"sym": "x"}, number(2))
                ),
            },
            "answer": {
                "expression": expression("mul", number(2), {"param": "a"}, {"sym": "x"})
            },
        },
        "parameters": [{"name": "a", "minimum": -1000000, "maximum": 1000000}],
    }
    qualification = qualify_math_template(
        template, settings=SamplingSettings(max_examples=50, seed=42)
    )
    return {
        "examples": results,
        "matched_examples": sum(r["matches"] for r in results),
        "qualification": qualification,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
