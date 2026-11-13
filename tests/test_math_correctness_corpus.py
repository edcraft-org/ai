"""Golden correctness corpus for the deterministic mathematics engine.

Every case is a complete request (problem plus candidate answer) with one
expected outcome.  The corpus deliberately mixes accepted answers with
correct-by-design refusals: an ``unknown`` or ``unsupported`` expectation is a
mathematical statement about the engine's scope, not a failure to decide.

The table in ``docs/math-correctness-coverage.md`` explains what each contract
decides and which answer forms are intentionally not assessed.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest
from edcraft_validator.domains.math.engine.dispatch import check_in_process

# ---------------------------------------------------------------------------
# Closed-IR builders


def num(value: int | str | Fraction) -> dict[str, object]:
    return {"num": str(value)}


def sym(name: str) -> dict[str, object]:
    return {"sym": name}


def op(name: str, *args: dict[str, object]) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def add(*args: dict[str, object]) -> dict[str, object]:
    return op("add", *args)


def mul(*args: dict[str, object]) -> dict[str, object]:
    return op("mul", *args)


def sub(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return op("sub", left, right)


def div(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return op("div", left, right)


def power(base: dict[str, object], exponent: object) -> dict[str, object]:
    return op("pow", base, num(exponent))  # type: ignore[arg-type]


def sqrt(inner: dict[str, object]) -> dict[str, object]:
    return op("sqrt", inner)


def log(inner: dict[str, object]) -> dict[str, object]:
    return op("log", inner)


def exp(inner: dict[str, object]) -> dict[str, object]:
    return op("exp", inner)


def sin(inner: dict[str, object]) -> dict[str, object]:
    return op("sin", inner)


def cos(inner: dict[str, object]) -> dict[str, object]:
    return op("cos", inner)


def absolute(inner: dict[str, object]) -> dict[str, object]:
    return op("abs", inner)


def neg(value: dict[str, object]) -> dict[str, object]:
    return sub(num(0), value)


def rel(kind: str, lhs: dict[str, object], rhs: dict[str, object]) -> dict[str, object]:
    return {"kind": kind, "lhs": lhs, "rhs": rhs}


def interval(
    lower: dict[str, object] | None,
    upper: dict[str, object] | None,
    *,
    lower_open: bool = True,
    upper_open: bool = True,
) -> dict[str, object]:
    return {
        "lower": lower,
        "upper": upper,
        "lower_open": lower_open,
        "upper_open": upper_open,
    }


def set_answer(
    items: list[dict[str, object]] | None = None,
    intervals: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    answer: dict[str, object] = {"kind": "set"}
    if items is not None:
        answer["items"] = items
    if intervals is not None:
        answer["intervals"] = intervals
    return answer


def expression_answer(expression: dict[str, object]) -> dict[str, object]:
    return {"kind": "expression", "expression": expression}


def tuple_answer(items: list[dict[str, object]]) -> dict[str, object]:
    return {"kind": "tuple", "items": items}


def matrix_answer(rows: list[list[object]]) -> dict[str, object]:
    return {"kind": "matrix", "matrix": matrix(rows)}


def lu_answer(
    permutation: list[list[object]],
    lower: list[list[object]],
    upper: list[list[object]],
) -> dict[str, object]:
    return {
        "kind": "lu",
        "permutation": matrix(permutation),
        "lower": matrix(lower),
        "upper": matrix(upper),
    }


def matrix(rows: list[list[object]]) -> list[list[dict[str, object]]]:
    return [
        [cell if isinstance(cell, dict) else num(cell) for cell in row]  # type: ignore[misc]
        for row in rows
    ]


X = {"name": "x"}
Y = {"name": "y"}
XY = [X, Y]
X_INT = {"name": "x", "domain": "integer"}
X_RAT = {"name": "x", "domain": "rational"}


def scalar_problem(
    operation: str,
    expression: dict[str, object],
    *,
    variable: str = "x",
    symbols: list[dict[str, object]] | None = None,
    lower: dict[str, object] | None = None,
    upper: dict[str, object] | None = None,
    order: int = 1,
) -> dict[str, object]:
    problem: dict[str, object] = {
        "operation": operation,
        "expression": expression,
        "variable": variable,
        "symbols": symbols if symbols is not None else [X],
    }
    if lower is not None:
        problem["lower"] = lower
    if upper is not None:
        problem["upper"] = upper
    if order != 1:
        problem["order"] = order
    return problem


def solve_problem(
    relations: list[dict[str, object]],
    *,
    solve_for: list[str] | None = None,
    symbols: list[dict[str, object]] | None = None,
    domain: str = "real",
) -> dict[str, object]:
    targets = solve_for if solve_for is not None else ["x"]
    return {
        "operation": "solve",
        "symbols": symbols if symbols is not None else [X],
        "relations": relations,
        "solve_for": targets,
        "domain": domain,
    }


def matrix_problem(
    operation: str,
    rows: list[list[object]],
    *,
    right_rows: list[list[object]] | None = None,
    symbols: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    problem: dict[str, object] = {
        "operation": operation,
        "matrix": matrix(rows),
    }
    if right_rows is not None:
        problem["right_matrix"] = matrix(right_rows)
    if symbols is not None:
        problem["symbols"] = symbols
    return problem


SCALAR = "expression"


def case(
    case_id: str,
    contract: str,
    problem: dict[str, object],
    answer: dict[str, object],
    expected_outcome: str,
    note: str,
) -> dict[str, object]:
    return {
        "id": case_id,
        "contract": contract,
        "problem": problem,
        "answer": answer,
        "expected_outcome": expected_outcome,
        "note": note,
    }


CASES: list[dict[str, object]] = []


# ---------------------------------------------------------------------------
# antiderivative


CASES.extend(
    [
        case(
            "antiderivative/power-rule",
            "antiderivative",
            scalar_problem("antiderivative", mul(num(2), sym("x"))),
            expression_answer(power(sym("x"), 2)),
            "correct",
            "d/dx x**2 = 2x",
        ),
        case(
            "antiderivative/additive-constant",
            "antiderivative",
            scalar_problem("antiderivative", mul(num(2), sym("x"))),
            expression_answer(add(power(sym("x"), 2), num(5))),
            "correct",
            "any additive constant is a valid primitive",
        ),
        case(
            "antiderivative/symbolic-constant",
            "antiderivative",
            scalar_problem(
                "antiderivative",
                mul(num(2), sym("x")),
                symbols=[X, {"name": "C"}],
            ),
            expression_answer(add(power(sym("x"), 2), sym("C"))),
            "correct",
            "a symbolic integration constant is accepted",
        ),
        case(
            "antiderivative/nonconstant-offset",
            "antiderivative",
            scalar_problem(
                "antiderivative",
                mul(num(2), sym("x")),
                symbols=[X, {"name": "C"}],
            ),
            expression_answer(add(power(sym("x"), 2), mul(sym("x"), sym("C")))),
            "incorrect",
            "x*C is not an additive constant",
        ),
        case(
            "antiderivative/reciprocal-absolute",
            "antiderivative",
            scalar_problem("antiderivative", div(num(1), sym("x"))),
            expression_answer(log(absolute(sym("x")))),
            "correct",
            "log|x| is a primitive on both branches of 1/x",
        ),
        case(
            "antiderivative/reciprocal-one-branch",
            "antiderivative",
            scalar_problem("antiderivative", div(num(1), sym("x"))),
            expression_answer(log(sym("x"))),
            "incorrect",
            "log(x) is undefined on the negative branch where 1/x is defined, "
            "so it fails the real-domain contract rather than differing in value",
        ),
        case(
            "antiderivative/cosine",
            "antiderivative",
            scalar_problem("antiderivative", cos(sym("x"))),
            expression_answer(sin(sym("x"))),
            "correct",
            "d/dx sin(x) = cos(x)",
        ),
        case(
            "antiderivative/wrong-sign",
            "antiderivative",
            scalar_problem("antiderivative", cos(sym("x"))),
            expression_answer(neg(sin(sym("x")))),
            "incorrect",
            "the sign of the primitive is wrong",
        ),
        case(
            "antiderivative/exponential",
            "antiderivative",
            scalar_problem("antiderivative", exp(sym("x"))),
            expression_answer(exp(sym("x"))),
            "correct",
            "exp is its own primitive",
        ),
        case(
            "antiderivative/inverse-square-root",
            "antiderivative",
            scalar_problem("antiderivative", div(num(1), sqrt(sym("x")))),
            expression_answer(mul(num(2), sqrt(sym("x")))),
            "correct",
            "d/dx 2*sqrt(x) = 1/sqrt(x) on x > 0",
        ),
        case(
            "antiderivative/chain-rule",
            "antiderivative",
            scalar_problem(
                "antiderivative",
                mul(num(2), sym("x"), exp(power(sym("x"), 2))),
            ),
            expression_answer(exp(power(sym("x"), 2))),
            "correct",
            "d/dx exp(x**2) = 2x*exp(x**2)",
        ),
        case(
            "antiderivative/inverse-square",
            "antiderivative",
            scalar_problem("antiderivative", div(num(1), power(sym("x"), 2))),
            expression_answer(neg(div(num(1), sym("x")))),
            "correct",
            "the primitive keeps the source hole at x = 0",
        ),
        case(
            "antiderivative/zero-integrand",
            "antiderivative",
            scalar_problem("antiderivative", num(0)),
            expression_answer(num(0)),
            "correct",
            "the zero function has the zero primitive",
        ),
        case(
            "antiderivative/missing-factor",
            "antiderivative",
            scalar_problem("antiderivative", mul(num(3), power(sym("x"), 2))),
            expression_answer(power(sym("x"), 2)),
            "incorrect",
            "x**2 differentiates to 2x, not 3x**2",
        ),
    ]
)


# ---------------------------------------------------------------------------
# complete-square


CASES.extend(
    [
        case(
            "complete-square/basic",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), mul(num(2), sym("x")), num(1)),
            ),
            expression_answer(power(add(sym("x"), num(1)), 2)),
            "correct",
            "x**2+2x+1 = (x+1)**2",
        ),
        case(
            "complete-square/negative-shift",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), mul(num(-4), sym("x")), num(4)),
            ),
            expression_answer(power(sub(sym("x"), num(2)), 2)),
            "correct",
            "x**2-4x+4 = (x-2)**2",
        ),
        case(
            "complete-square/vertex-form",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), mul(num(6), sym("x")), num(5)),
            ),
            expression_answer(
                sub(power(add(sym("x"), num(3)), 2), num(4)),
            ),
            "correct",
            "x**2+6x+5 = (x+3)**2-4",
        ),
        case(
            "complete-square/leading-coefficient",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(
                    mul(num(2), power(sym("x"), 2)),
                    mul(num(-8), sym("x")),
                    num(1),
                ),
            ),
            expression_answer(
                sub(mul(num(2), power(sub(sym("x"), num(2)), 2)), num(7)),
            ),
            "correct",
            "2x**2-8x+1 = 2(x-2)**2-7",
        ),
        case(
            "complete-square/negative-leading",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(neg(power(sym("x"), 2)), mul(num(2), sym("x")), num(-1)),
            ),
            expression_answer(neg(power(sub(sym("x"), num(1)), 2))),
            "correct",
            "-x**2+2x-1 = -(x-1)**2",
        ),
        case(
            "complete-square/rational-vertex",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), sym("x"), num(1)),
            ),
            expression_answer(
                add(power(add(sym("x"), num(Fraction(1, 2))), 2), num(Fraction(3, 4))),
            ),
            "correct",
            "x**2+x+1 = (x+1/2)**2+3/4",
        ),
        case(
            "complete-square/factored-form-passes",
            "complete-square",
            scalar_problem(
                "complete-square",
                sub(power(sym("x"), 2), num(1)),
            ),
            expression_answer(mul(sub(sym("x"), num(1)), add(sym("x"), num(1)))),
            "correct",
            "answer form is not assessed; algebraic equivalence is",
        ),
        case(
            "complete-square/unchanged-expression",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), mul(num(2), sym("x")), num(1)),
            ),
            expression_answer(
                add(power(sym("x"), 2), mul(num(2), sym("x")), num(1)),
            ),
            "correct",
            "an unchanged but equivalent expression passes",
        ),
        case(
            "complete-square/wrong-constant",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), mul(num(4), sym("x")), num(1)),
            ),
            expression_answer(sub(power(add(sym("x"), num(2)), 2), num(4))),
            "incorrect",
            "the completed square has the wrong constant",
        ),
        case(
            "complete-square/wrong-leading-scale",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(
                    mul(num(2), power(sym("x"), 2)),
                    mul(num(-8), sym("x")),
                    num(1),
                ),
            ),
            expression_answer(sub(power(sub(sym("x"), num(2)), 2), num(7))),
            "incorrect",
            "the leading coefficient 2 is missing",
        ),
        case(
            "complete-square/rational-wrong-constant",
            "complete-square",
            scalar_problem(
                "complete-square",
                add(power(sym("x"), 2), sym("x"), num(1)),
            ),
            expression_answer(
                add(power(add(sym("x"), num(Fraction(1, 2))), 2), num(Fraction(1, 2))),
            ),
            "incorrect",
            "3/4, not 1/2, completes the square",
        ),
    ]
)


# ---------------------------------------------------------------------------
# definite-integral


CASES.extend(
    [
        case(
            "definite-integral/power",
            "definite-integral",
            scalar_problem(
                "definite-integral", power(sym("x"), 2), lower=num(0), upper=num(1)
            ),
            expression_answer(num(Fraction(1, 3))),
            "correct",
            "integral of x**2 on [0,1] is 1/3",
        ),
        case(
            "definite-integral/power-wrong",
            "definite-integral",
            scalar_problem(
                "definite-integral", power(sym("x"), 2), lower=num(0), upper=num(1)
            ),
            expression_answer(num(Fraction(1, 4))),
            "incorrect",
            "the exact value is 1/3",
        ),
        case(
            "definite-integral/reversed-bounds",
            "definite-integral",
            scalar_problem(
                "definite-integral", power(sym("x"), 2), lower=num(1), upper=num(0)
            ),
            expression_answer(num(Fraction(-1, 3))),
            "correct",
            "reversing the bounds negates the integral",
        ),
        case(
            "definite-integral/reversed-upper-power",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                sub(power(sym("x"), 2), num(1)),
                lower=num(2),
                upper=num(0),
            ),
            expression_answer(num(Fraction(-2, 3))),
            "correct",
            "reversed bounds of x**2-1 on [0,2]",
        ),
        case(
            "definite-integral/equal-bounds",
            "definite-integral",
            scalar_problem(
                "definite-integral", power(sym("x"), 2), lower=num(2), upper=num(2)
            ),
            expression_answer(num(0)),
            "correct",
            "an integral over a point is zero",
        ),
        case(
            "definite-integral/constant",
            "definite-integral",
            scalar_problem("definite-integral", num(3), lower=num(-1), upper=num(1)),
            expression_answer(num(6)),
            "correct",
            "the area of a 3 by 2 rectangle",
        ),
        case(
            "definite-integral/sine-half-period",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                sin(sym("x")),
                lower=num(0),
                upper=div(op("acos", num(-1)), num(2)),
            ),
            expression_answer(num(1)),
            "correct",
            "integral of sin on [0, pi/2]",
        ),
        case(
            "definite-integral/sine-full-period",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                sin(sym("x")),
                lower=num(0),
                upper=op("acos", num(-1)),
            ),
            expression_answer(num(2)),
            "correct",
            "integral of sin on [0, pi]",
        ),
        case(
            "definite-integral/exponential",
            "definite-integral",
            scalar_problem(
                "definite-integral", exp(sym("x")), lower=num(0), upper=num(1)
            ),
            expression_answer(sub(exp(num(1)), num(1))),
            "correct",
            "integral of exp on [0,1] is e-1",
        ),
        case(
            "definite-integral/logarithm",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                div(num(1), sym("x")),
                lower=num(1),
                upper=exp(num(1)),
            ),
            expression_answer(num(1)),
            "correct",
            "integral of 1/x on [1,e] is 1",
        ),
        case(
            "definite-integral/interior-singularity",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                div(num(1), sym("x")),
                lower=num(-1),
                upper=num(1),
            ),
            expression_answer(num(0)),
            "unknown",
            "an interior pole is an improper integral the engine refuses",
        ),
        case(
            "definite-integral/endpoint-singularity",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                div(num(1), sqrt(sym("x"))),
                lower=num(0),
                upper=num(1),
            ),
            expression_answer(num(2)),
            "unknown",
            "the integrand is unbounded at an endpoint",
        ),
        case(
            "definite-integral/symbolic-endpoint",
            "definite-integral",
            scalar_problem(
                "definite-integral",
                power(sym("x"), 2),
                lower=sym("x"),
                upper=num(1),
            ),
            expression_answer(num(Fraction(1, 3))),
            "unsupported",
            "endpoints must be finite real constants",
        ),
    ]
)


# ---------------------------------------------------------------------------
# differentiate


CASES.extend(
    [
        case(
            "differentiate/power-rule",
            "differentiate",
            scalar_problem("differentiate", power(sym("x"), 3)),
            expression_answer(mul(num(3), power(sym("x"), 2))),
            "correct",
            "d/dx x**3 = 3x**2",
        ),
        case(
            "differentiate/second-order",
            "differentiate",
            scalar_problem("differentiate", power(sym("x"), 3), order=2),
            expression_answer(mul(num(6), sym("x"))),
            "correct",
            "the second derivative of x**3 is 6x",
        ),
        case(
            "differentiate/third-order",
            "differentiate",
            scalar_problem("differentiate", power(sym("x"), 4), order=3),
            expression_answer(mul(num(24), sym("x"))),
            "correct",
            "the third derivative of x**4 is 24x",
        ),
        case(
            "differentiate/product-rule",
            "differentiate",
            scalar_problem("differentiate", mul(sym("x"), sin(sym("x")))),
            expression_answer(
                add(sin(sym("x")), mul(sym("x"), cos(sym("x")))),
            ),
            "correct",
            "product rule for x*sin(x)",
        ),
        case(
            "differentiate/chain-rule",
            "differentiate",
            scalar_problem("differentiate", sin(power(sym("x"), 2))),
            expression_answer(mul(num(2), sym("x"), cos(power(sym("x"), 2)))),
            "correct",
            "chain rule for sin(x**2)",
        ),
        case(
            "differentiate/chain-rule-wrong",
            "differentiate",
            scalar_problem("differentiate", sin(power(sym("x"), 2))),
            expression_answer(cos(power(sym("x"), 2))),
            "incorrect",
            "the inner derivative 2x is missing",
        ),
        case(
            "differentiate/quotient-rule",
            "differentiate",
            scalar_problem("differentiate", div(power(sym("x"), 2), sym("x"))),
            expression_answer(num(1)),
            "correct",
            "x**2/x differentiates to 1 on x != 0",
        ),
        case(
            "differentiate/quotient-singularity",
            "differentiate",
            scalar_problem("differentiate", sym("x")),
            expression_answer(div(sym("x"), sym("x"))),
            "incorrect",
            "x/x introduces a hole at x = 0 where x is differentiable, so the "
            "real-domain contract refuses it (not a value difference)",
        ),
        case(
            "differentiate/square-root",
            "differentiate",
            scalar_problem("differentiate", sqrt(sym("x"))),
            expression_answer(div(num(1), mul(num(2), sqrt(sym("x"))))),
            "correct",
            "d/dx sqrt(x) = 1/(2 sqrt(x))",
        ),
        case(
            "differentiate/exponential-chain",
            "differentiate",
            scalar_problem("differentiate", exp(mul(num(2), sym("x")))),
            expression_answer(mul(num(2), exp(mul(num(2), sym("x"))))),
            "correct",
            "d/dx exp(2x) = 2 exp(2x)",
        ),
        case(
            "differentiate/logarithm",
            "differentiate",
            scalar_problem("differentiate", log(sym("x"))),
            expression_answer(div(num(1), sym("x"))),
            "correct",
            "d/dx log(x) = 1/x on x > 0",
        ),
        case(
            "differentiate/tangent",
            "differentiate",
            scalar_problem("differentiate", op("tan", sym("x"))),
            expression_answer(add(num(1), power(op("tan", sym("x")), 2))),
            "correct",
            "1+tan(x)**2 is the derivative of tan(x)",
        ),
        case(
            "differentiate/constant",
            "differentiate",
            scalar_problem("differentiate", num(5)),
            expression_answer(num(0)),
            "correct",
            "constants have zero derivative",
        ),
        case(
            "differentiate/wrong-power",
            "differentiate",
            scalar_problem("differentiate", power(sym("x"), 3)),
            expression_answer(mul(num(3), sym("x"))),
            "incorrect",
            "the exponent was not reduced",
        ),
    ]
)


# ---------------------------------------------------------------------------
# expand


CASES.extend(
    [
        case(
            "expand/binomial-square",
            "expand",
            scalar_problem("expand", power(add(sym("x"), num(1)), 2)),
            expression_answer(
                add(power(sym("x"), 2), mul(num(2), sym("x")), num(1)),
            ),
            "correct",
            "(x+1)**2 expands to x**2+2x+1",
        ),
        case(
            "expand/binomial-square-wrong",
            "expand",
            scalar_problem("expand", power(add(sym("x"), num(1)), 2)),
            expression_answer(add(power(sym("x"), 2), num(1))),
            "incorrect",
            "the cross term is missing",
        ),
        case(
            "expand/difference-of-squares",
            "expand",
            scalar_problem("expand", mul(add(sym("x"), num(1)), sub(sym("x"), num(1)))),
            expression_answer(sub(power(sym("x"), 2), num(1))),
            "correct",
            "(x+1)(x-1) = x**2-1",
        ),
        case(
            "expand/binomial-cube",
            "expand",
            scalar_problem("expand", power(add(sym("x"), num(2)), 3)),
            expression_answer(
                add(
                    power(sym("x"), 3),
                    mul(num(6), power(sym("x"), 2)),
                    mul(num(12), sym("x")),
                    num(8),
                ),
            ),
            "correct",
            "(x+2)**3 expands exactly",
        ),
        case(
            "expand/binomial-cube-wrong",
            "expand",
            scalar_problem("expand", power(add(sym("x"), num(2)), 3)),
            expression_answer(add(power(sym("x"), 3), num(8))),
            "incorrect",
            "the middle terms are missing",
        ),
        case(
            "expand/two-variables",
            "expand",
            scalar_problem("expand", power(add(sym("x"), sym("y")), 2), symbols=XY),
            expression_answer(
                add(
                    power(sym("x"), 2),
                    mul(num(2), sym("x"), sym("y")),
                    power(sym("y"), 2),
                ),
            ),
            "correct",
            "(x+y)**2 = x**2+2xy+y**2",
        ),
        case(
            "expand/two-variables-wrong",
            "expand",
            scalar_problem("expand", power(add(sym("x"), sym("y")), 2), symbols=XY),
            expression_answer(add(power(sym("x"), 2), power(sym("y"), 2))),
            "incorrect",
            "the cross term 2xy is missing",
        ),
        case(
            "expand/product-of-binomials",
            "expand",
            scalar_problem(
                "expand",
                mul(
                    sub(mul(num(2), sym("x")), num(3)),
                    add(sym("x"), num(4)),
                ),
            ),
            expression_answer(
                add(
                    mul(num(2), power(sym("x"), 2)),
                    mul(num(5), sym("x")),
                    num(-12),
                ),
            ),
            "correct",
            "(2x-3)(x+4) = 2x**2+5x-12",
        ),
        case(
            "expand/factored-answer-passes",
            "expand",
            scalar_problem("expand", power(add(sym("x"), num(1)), 2)),
            expression_answer(mul(add(sym("x"), num(1)), add(sym("x"), num(1)))),
            "correct",
            "answer form is not assessed; factored forms pass",
        ),
        case(
            "expand/distribute-monomial",
            "expand",
            scalar_problem("expand", mul(sym("x"), add(sym("x"), num(1)))),
            expression_answer(add(power(sym("x"), 2), sym("x"))),
            "correct",
            "x(x+1) = x**2+x",
        ),
        case(
            "expand/difference-of-squares-two-variables",
            "expand",
            scalar_problem(
                "expand",
                mul(add(sym("x"), sym("y")), sub(sym("x"), sym("y"))),
                symbols=XY,
            ),
            expression_answer(sub(power(sym("x"), 2), power(sym("y"), 2))),
            "correct",
            "(x+y)(x-y) = x**2-y**2",
        ),
        case(
            "expand/off-by-one",
            "expand",
            scalar_problem("expand", power(add(sym("x"), num(1)), 2)),
            expression_answer(
                add(power(sym("x"), 2), mul(num(2), sym("x")), num(2)),
            ),
            "incorrect",
            "the constant should be 1",
        ),
        case(
            "expand/restricted-source-domain",
            "expand",
            scalar_problem("expand", power(sqrt(sym("x")), 2)),
            expression_answer(sym("x")),
            "correct",
            "(sqrt(x))**2 equals x on the source domain x >= 0",
        ),
        case(
            "expand/sqrt-product-needs-nonnegative-factors",
            "expand",
            scalar_problem("expand", sqrt(mul(sym("x"), sym("y"))), symbols=XY),
            expression_answer(mul(sqrt(sym("x")), sqrt(sym("y")))),
            "incorrect",
            "sqrt(x)*sqrt(y) = sqrt(x*y) needs nonnegative factors, not just a "
            "signed product: the source fixes only x*y >= 0, and even the strict "
            "guard x*y > 0 admits x = y = -2, where the candidate is not real. "
            "This is a real-domain failure, not a value difference.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# factor


CASES.extend(
    [
        case(
            "factor/difference-of-squares",
            "factor",
            scalar_problem("factor", sub(power(sym("x"), 2), num(1))),
            expression_answer(
                mul(sub(sym("x"), num(1)), add(sym("x"), num(1))),
            ),
            "correct",
            "x**2-1 = (x-1)(x+1)",
        ),
        case(
            "factor/difference-of-squares-wrong",
            "factor",
            scalar_problem("factor", sub(power(sym("x"), 2), num(1))),
            expression_answer(power(sub(sym("x"), num(1)), 2)),
            "incorrect",
            "the second factor was squared by mistake",
        ),
        case(
            "factor/perfect-square",
            "factor",
            scalar_problem(
                "factor",
                add(power(sym("x"), 2), mul(num(2), sym("x")), num(1)),
            ),
            expression_answer(power(add(sym("x"), num(1)), 2)),
            "correct",
            "x**2+2x+1 = (x+1)**2",
        ),
        case(
            "factor/monic-quadratic",
            "factor",
            scalar_problem(
                "factor",
                add(power(sym("x"), 2), mul(num(-5), sym("x")), num(6)),
            ),
            expression_answer(
                mul(sub(sym("x"), num(2)), sub(sym("x"), num(3))),
            ),
            "correct",
            "x**2-5x+6 = (x-2)(x-3)",
        ),
        case(
            "factor/monic-quadratic-wrong",
            "factor",
            scalar_problem(
                "factor",
                add(power(sym("x"), 2), mul(num(-5), sym("x")), num(6)),
            ),
            expression_answer(
                mul(sub(sym("x"), num(2)), add(sym("x"), num(3))),
            ),
            "incorrect",
            "the roots 2 and -3 do not match",
        ),
        case(
            "factor/cubic-with-zero-root",
            "factor",
            scalar_problem(
                "factor",
                sub(power(sym("x"), 3), sym("x")),
            ),
            expression_answer(
                mul(
                    sym("x"),
                    sub(sym("x"), num(1)),
                    add(sym("x"), num(1)),
                ),
            ),
            "correct",
            "x**3-x = x(x-1)(x+1)",
        ),
        case(
            "factor/irreducible-unchanged",
            "factor",
            scalar_problem("factor", add(power(sym("x"), 2), num(1))),
            expression_answer(add(power(sym("x"), 2), num(1))),
            "correct",
            "an irreducible quadratic may stay unchanged",
        ),
        case(
            "factor/scaled-quadratic",
            "factor",
            scalar_problem(
                "factor",
                sub(mul(num(2), power(sym("x"), 2)), num(2)),
            ),
            expression_answer(
                mul(
                    num(2),
                    sub(sym("x"), num(1)),
                    add(sym("x"), num(1)),
                ),
            ),
            "correct",
            "2x**2-2 = 2(x-1)(x+1)",
        ),
        case(
            "factor/sum-of-cubes",
            "factor",
            scalar_problem("factor", add(power(sym("x"), 3), num(1))),
            expression_answer(
                mul(
                    add(sym("x"), num(1)),
                    add(power(sym("x"), 2), neg(sym("x")), num(1)),
                ),
            ),
            "correct",
            "x**3+1 = (x+1)(x**2-x+1)",
        ),
        case(
            "factor/sum-of-cubes-wrong",
            "factor",
            scalar_problem("factor", add(power(sym("x"), 3), num(1))),
            expression_answer(power(add(sym("x"), num(1)), 3)),
            "incorrect",
            "(x+1)**3 is not x**3+1",
        ),
        case(
            "factor/two-variables",
            "factor",
            scalar_problem(
                "factor", sub(power(sym("x"), 2), power(sym("y"), 2)), symbols=XY
            ),
            expression_answer(mul(sub(sym("x"), sym("y")), add(sym("x"), sym("y")))),
            "correct",
            "x**2-y**2 = (x-y)(x+y)",
        ),
        case(
            "factor/common-monomial",
            "factor",
            scalar_problem("factor", add(power(sym("x"), 2), sym("x"))),
            expression_answer(mul(sym("x"), add(sym("x"), num(1)))),
            "correct",
            "x**2+x = x(x+1)",
        ),
    ]
)


# ---------------------------------------------------------------------------
# determinant


CASES.extend(
    [
        case(
            "determinant/two-by-two",
            "determinant",
            matrix_problem("determinant", [[1, 2], [3, 4]]),
            expression_answer(num(-2)),
            "correct",
            "det [[1,2],[3,4]] = -2",
        ),
        case(
            "determinant/two-by-two-wrong",
            "determinant",
            matrix_problem("determinant", [[1, 2], [3, 4]]),
            expression_answer(num(-1)),
            "incorrect",
            "the exact determinant is -2",
        ),
        case(
            "determinant/three-by-three",
            "determinant",
            matrix_problem("determinant", [[1, 2, 3], [4, 5, 6], [7, 8, 10]]),
            expression_answer(num(-3)),
            "correct",
            "det of [[1,2,3],[4,5,6],[7,8,10]] = -3",
        ),
        case(
            "determinant/three-by-three-wrong",
            "determinant",
            matrix_problem("determinant", [[1, 2, 3], [4, 5, 6], [7, 8, 10]]),
            expression_answer(num(0)),
            "incorrect",
            "the matrix is nonsingular",
        ),
        case(
            "determinant/one-by-one",
            "determinant",
            matrix_problem("determinant", [[7]]),
            expression_answer(num(7)),
            "correct",
            "the determinant of a 1x1 matrix is its entry",
        ),
        case(
            "determinant/singular",
            "determinant",
            matrix_problem(
                "determinant",
                [[1, 2, 3], [2, 4, 6], [1, 1, 1]],
            ),
            expression_answer(num(0)),
            "correct",
            "a repeated row makes the determinant zero",
        ),
        case(
            "determinant/triangular",
            "determinant",
            matrix_problem(
                "determinant",
                [[2, 5, 1], [0, 3, 7], [0, 0, 4]],
            ),
            expression_answer(num(24)),
            "correct",
            "the determinant of a triangular matrix is the diagonal product",
        ),
        case(
            "determinant/rational-entries",
            "determinant",
            matrix_problem(
                "determinant",
                [
                    [Fraction(1, 2), Fraction(1, 3)],
                    [Fraction(1, 4), Fraction(1, 5)],
                ],
            ),
            expression_answer(num(Fraction(1, 60))),
            "correct",
            "exact rational determinant 1/60",
        ),
        case(
            "determinant/radical-entries",
            "determinant",
            matrix_problem("determinant", [[sqrt(num(2)), 0], [0, sqrt(num(2))]]),
            expression_answer(num(2)),
            "correct",
            "the determinant is (sqrt(2))**2 = 2",
        ),
        case(
            "determinant/radical-wrong",
            "determinant",
            matrix_problem("determinant", [[sqrt(num(2)), 0], [0, sqrt(num(2))]]),
            expression_answer(num(4)),
            "incorrect",
            "the determinant is not 4",
        ),
        case(
            "determinant/four-by-four",
            "determinant",
            matrix_problem(
                "determinant",
                [
                    [2, 1, 0, 3],
                    [1, -1, 2, 0],
                    [3, 0, 1, 1],
                    [0, 2, 1, 4],
                ],
            ),
            expression_answer(num(-16)),
            "correct",
            "the 4x4 determinant is -16",
        ),
        case(
            "determinant/five-by-five",
            "determinant",
            matrix_problem(
                "determinant",
                [
                    [2, 1, 0, 0, 0],
                    [1, 3, 1, 0, 0],
                    [0, 1, 4, 1, 0],
                    [0, 0, 1, 5, 1],
                    [0, 0, 0, 1, 6],
                ],
            ),
            expression_answer(num(492)),
            "correct",
            "the 5x5 tridiagonal determinant is 492",
        ),
        case(
            "determinant/matrix-answer-unsupported",
            "determinant",
            matrix_problem("determinant", [[1, 2], [3, 4]]),
            matrix_answer([[-2]]),
            "unsupported",
            "a determinant answer must be an expression",
        ),
        case(
            "determinant/non-square-unsupported",
            "determinant",
            matrix_problem("determinant", [[1, 2, 3], [4, 5, 6]]),
            expression_answer(num(0)),
            "unsupported",
            "the determinant is only defined for square matrices",
        ),
    ]
)


# ---------------------------------------------------------------------------
# inverse


CASES.extend(
    [
        case(
            "inverse/two-by-two",
            "inverse",
            matrix_problem("inverse", [[4, 7], [2, 6]]),
            matrix_answer(
                [
                    [Fraction(3, 5), Fraction(-7, 10)],
                    [Fraction(-1, 5), Fraction(2, 5)],
                ]
            ),
            "correct",
            "the exact inverse of [[4,7],[2,6]]",
        ),
        case(
            "inverse/two-by-two-wrong-entry",
            "inverse",
            matrix_problem("inverse", [[4, 7], [2, 6]]),
            matrix_answer(
                [
                    [Fraction(3, 5), Fraction(7, 10)],
                    [Fraction(-1, 5), Fraction(2, 5)],
                ]
            ),
            "incorrect",
            "one sign is wrong",
        ),
        case(
            "inverse/one-by-one",
            "inverse",
            matrix_problem("inverse", [[7]]),
            matrix_answer([[Fraction(1, 7)]]),
            "correct",
            "the inverse of [7] is [1/7]",
        ),
        case(
            "inverse/singular-unsupported",
            "inverse",
            matrix_problem("inverse", [[1, 2], [2, 4]]),
            matrix_answer([[1, 0], [0, 1]]),
            "unsupported",
            "a singular matrix has no inverse",
        ),
        case(
            "inverse/identity",
            "inverse",
            matrix_problem("inverse", [[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
            matrix_answer([[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
            "correct",
            "the identity is its own inverse",
        ),
        case(
            "inverse/diagonal",
            "inverse",
            matrix_problem("inverse", [[2, 0, 0], [0, 3, 0], [0, 0, 4]]),
            matrix_answer(
                [
                    [Fraction(1, 2), 0, 0],
                    [0, Fraction(1, 3), 0],
                    [0, 0, Fraction(1, 4)],
                ]
            ),
            "correct",
            "diagonal entries invert individually",
        ),
        case(
            "inverse/radical",
            "inverse",
            matrix_problem("inverse", [[2, 0], [0, sqrt(num(2))]]),
            matrix_answer(
                [
                    [Fraction(1, 2), 0],
                    [0, div(num(1), sqrt(num(2)))],
                ]
            ),
            "correct",
            "an exact radical inverse is accepted",
        ),
        case(
            "inverse/three-by-three",
            "inverse",
            matrix_problem("inverse", [[1, 2, 0], [0, 1, 0], [0, 0, 1]]),
            matrix_answer([[1, -2, 0], [0, 1, 0], [0, 0, 1]]),
            "correct",
            "the inverse of a shear is the opposite shear",
        ),
        case(
            "inverse/three-by-three-wrong",
            "inverse",
            matrix_problem("inverse", [[1, 2, 0], [0, 1, 0], [0, 0, 1]]),
            matrix_answer([[1, 2, 0], [0, 1, 0], [0, 0, 1]]),
            "incorrect",
            "the shear sign is not reversed",
        ),
        case(
            "inverse/wrong-shape",
            "inverse",
            matrix_problem("inverse", [[1, 2], [3, 4]]),
            matrix_answer([[1, 0], [0, 1]]),
            "incorrect",
            "the candidate has the wrong numeric entries for this matrix",
        ),
        case(
            "inverse/four-by-four",
            "inverse",
            matrix_problem(
                "inverse",
                [
                    [4, 7, 2, 1],
                    [3, 6, 1, 0],
                    [2, 5, 3, 1],
                    [1, 2, 0, 5],
                ],
            ),
            matrix_answer(
                [
                    [
                        Fraction(67, 47),
                        Fraction(-53, 47),
                        Fraction(-27, 47),
                        Fraction(-8, 47),
                    ],
                    [
                        Fraction(-36, 47),
                        Fraction(39, 47),
                        Fraction(11, 47),
                        Fraction(5, 47),
                    ],
                    [
                        Fraction(15, 47),
                        Fraction(-28, 47),
                        Fraction(15, 47),
                        Fraction(-6, 47),
                    ],
                    [
                        Fraction(1, 47),
                        Fraction(-5, 47),
                        Fraction(1, 47),
                        Fraction(9, 47),
                    ],
                ]
            ),
            "correct",
            "the 4x4 inverse is verified by both exact products",
        ),
        case(
            "inverse/expression-answer-unsupported",
            "inverse",
            matrix_problem("inverse", [[1, 2], [3, 4]]),
            expression_answer(num(1)),
            "unsupported",
            "an inverse answer must be a matrix",
        ),
        case(
            "inverse/non-square-unsupported",
            "inverse",
            matrix_problem("inverse", [[1, 2, 3], [4, 5, 6]]),
            matrix_answer([[1, 0], [0, 1]]),
            "unsupported",
            "only square matrices can be inverted",
        ),
        case(
            "inverse/two-by-two-identity-check",
            "inverse",
            matrix_problem("inverse", [[1, 1], [1, 2]]),
            matrix_answer([[2, -1], [-1, 1]]),
            "correct",
            "the exact inverse of [[1,1],[1,2]]",
        ),
    ]
)


# ---------------------------------------------------------------------------
# lu


LU_MATRIX = [[2, 1], [4, 3]]
LU_STANDARD_LOWER = [[1, 0], [2, 1]]
LU_STANDARD_UPPER = [[2, 1], [0, 1]]
LU_IDENTITY = [[1, 0], [0, 1]]

CASES.extend(
    [
        case(
            "lu/standard",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(LU_IDENTITY, LU_STANDARD_LOWER, LU_STANDARD_UPPER),
            "correct",
            "the standard unit-lower LU decomposition",
        ),
        case(
            "lu/alternate-pivot",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                [[0, 1], [1, 0]],
                [[1, 0], [Fraction(1, 2), 1]],
                [[4, 3], [0, Fraction(-1, 2)]],
            ),
            "correct",
            "a row swap gives another valid decomposition",
        ),
        case(
            "lu/non-permutation",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                [[1, 1], [0, 0]],
                LU_STANDARD_LOWER,
                LU_STANDARD_UPPER,
            ),
            "incorrect",
            "P must be a permutation matrix",
        ),
        case(
            "lu/non-unit-lower",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                LU_IDENTITY,
                [[2, 0], [4, 2]],
                [[1, Fraction(1, 2)], [0, Fraction(1, 2)]],
            ),
            "incorrect",
            "L must be unit lower triangular",
        ),
        case(
            "lu/product-mismatch",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                LU_IDENTITY,
                LU_STANDARD_LOWER,
                [[2, 1], [0, 2]],
            ),
            "incorrect",
            "L*U does not equal P*A",
        ),
        case(
            "lu/lower-not-triangular",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                LU_IDENTITY,
                [[1, 1], [2, 1]],
                LU_STANDARD_UPPER,
            ),
            "incorrect",
            "L has an entry above the diagonal",
        ),
        case(
            "lu/upper-not-triangular",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                LU_IDENTITY,
                LU_STANDARD_LOWER,
                [[2, 1], [1, 1]],
            ),
            "incorrect",
            "U has an entry below the diagonal",
        ),
        case(
            "lu/wrong-permutation-shape",
            "lu",
            matrix_problem("lu", LU_MATRIX),
            lu_answer(
                [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                LU_STANDARD_LOWER,
                LU_STANDARD_UPPER,
            ),
            "incorrect",
            "P has the wrong dimension",
        ),
        case(
            "lu/one-by-one",
            "lu",
            matrix_problem("lu", [[7]]),
            lu_answer([[1]], [[1]], [[7]]),
            "correct",
            "the 1x1 decomposition is P=L=[1], U=[7]",
        ),
        case(
            "lu/three-cycle-permutation",
            "lu",
            matrix_problem(
                "lu",
                [[0, 0, 6], [1, 2, 3], [0, 4, 5]],
            ),
            lu_answer(
                [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
                [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                [[1, 2, 3], [0, 4, 5], [0, 0, 6]],
            ),
            "correct",
            "a 3-cycle P is accepted when P*A = L*U",
        ),
        case(
            "lu/singular",
            "lu",
            matrix_problem("lu", [[1, 1], [1, 1]]),
            lu_answer(
                LU_IDENTITY,
                [[1, 0], [1, 1]],
                [[1, 1], [0, 0]],
            ),
            "correct",
            "a singular matrix still has an LU decomposition",
        ),
        case(
            "lu/non-square-unsupported",
            "lu",
            matrix_problem("lu", [[1, 2, 3], [4, 5, 6]]),
            lu_answer(LU_IDENTITY, LU_STANDARD_LOWER, LU_STANDARD_UPPER),
            "unsupported",
            "LU decomposition requires a square matrix",
        ),
        case(
            "lu/three-by-three-standard",
            "lu",
            matrix_problem(
                "lu",
                [[1, 2, 3], [4, 5, 6], [7, 8, 10]],
            ),
            lu_answer(
                [[1, 0, 0], [4, 1, 0], [7, 2, 1]],
                [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                [[1, 2, 3], [0, 5, 6], [0, 0, 10]],
            ),
            "incorrect",
            "the listed L and U do not reproduce this matrix",
        ),
    ]
)


# ---------------------------------------------------------------------------
# matrix-multiply


CASES.extend(
    [
        case(
            "matrix-multiply/two-by-two",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply", [[1, 2], [3, 4]], right_rows=[[5, 6], [7, 8]]
            ),
            matrix_answer([[19, 22], [43, 50]]),
            "correct",
            "the exact 2x2 product",
        ),
        case(
            "matrix-multiply/two-by-two-wrong",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply", [[1, 2], [3, 4]], right_rows=[[5, 6], [7, 8]]
            ),
            matrix_answer([[19, 22], [43, 49]]),
            "incorrect",
            "one entry is off by one",
        ),
        case(
            "matrix-multiply/identity",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply", [[1, 2], [3, 4]], right_rows=[[1, 0], [0, 1]]
            ),
            matrix_answer([[1, 2], [3, 4]]),
            "correct",
            "multiplying by the identity",
        ),
        case(
            "matrix-multiply/rectangular",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply",
                [[1, 2, 3, 0, 1], [4, 5, 6, 1, 0], [7, 8, 9, 2, 1]],
                right_rows=[[1, 0], [0, 1], [1, 1], [2, -1], [-1, 2]],
            ),
            matrix_answer([[3, 7], [12, 10], [19, 17]]),
            "correct",
            "a 3x5 times a 5x2 product",
        ),
        case(
            "matrix-multiply/rectangular-wrong",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply",
                [[1, 2, 3, 0, 1], [4, 5, 6, 1, 0], [7, 8, 9, 2, 1]],
                right_rows=[[1, 0], [0, 1], [1, 1], [2, -1], [-1, 2]],
            ),
            matrix_answer([[3, 7], [12, 10], [19, 16]]),
            "incorrect",
            "the last entry should be 17",
        ),
        case(
            "matrix-multiply/inner-dimension-mismatch",
            "matrix-multiply",
            matrix_problem("matrix-multiply", [[1, 2]], right_rows=[[1], [2], [3]]),
            matrix_answer([[1], [2]]),
            "unsupported",
            "inner dimensions must agree",
        ),
        case(
            "matrix-multiply/wrong-shape",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply", [[1, 2], [3, 4]], right_rows=[[0, 1], [1, 0]]
            ),
            matrix_answer([[2, 1, 0], [4, 3, 0]]),
            "incorrect",
            "the candidate product has an extra column",
        ),
        case(
            "matrix-multiply/one-by-one",
            "matrix-multiply",
            matrix_problem("matrix-multiply", [[3]], right_rows=[[4]]),
            matrix_answer([[12]]),
            "correct",
            "scalar multiplication as 1x1 matrices",
        ),
        case(
            "matrix-multiply/row-times-column",
            "matrix-multiply",
            matrix_problem("matrix-multiply", [[1, 2, 3]], right_rows=[[1], [2], [3]]),
            matrix_answer([[14]]),
            "correct",
            "a dot product written as a matrix product",
        ),
        case(
            "matrix-multiply/outer-product",
            "matrix-multiply",
            matrix_problem("matrix-multiply", [[1], [2], [3]], right_rows=[[1, 2]]),
            matrix_answer([[1, 2], [2, 4], [3, 6]]),
            "correct",
            "a column times a row is an outer product",
        ),
        case(
            "matrix-multiply/rational-entries",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply",
                [
                    [Fraction(1, 2), Fraction(1, 3)],
                    [Fraction(1, 4), Fraction(1, 5)],
                ],
                right_rows=[[1, 0], [0, 1]],
            ),
            matrix_answer(
                [
                    [Fraction(1, 2), Fraction(1, 3)],
                    [Fraction(1, 4), Fraction(1, 5)],
                ]
            ),
            "correct",
            "exact rational entries are preserved",
        ),
        case(
            "matrix-multiply/permutation",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply",
                [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
                right_rows=[[0, 1, 0], [1, 0, 0], [0, 0, 1]],
            ),
            matrix_answer([[2, 1, 3], [5, 4, 6], [8, 7, 9]]),
            "correct",
            "right multiplication swaps two columns",
        ),
        case(
            "matrix-multiply/expression-answer-unsupported",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply", [[1, 2], [3, 4]], right_rows=[[1, 0], [0, 1]]
            ),
            expression_answer(num(1)),
            "unsupported",
            "a product answer must be a matrix",
        ),
        case(
            "matrix-multiply/eight-by-eight",
            "matrix-multiply",
            matrix_problem(
                "matrix-multiply",
                [[i + 1 if i == j else 0 for j in range(8)] for i in range(8)],
                right_rows=[[1 if i == j else 0 for j in range(8)] for i in range(8)],
            ),
            matrix_answer(
                [[i + 1 if i == j else 0 for j in range(8)] for i in range(8)]
            ),
            "correct",
            "an 8x8 diagonal product stays exact",
        ),
    ]
)


# ---------------------------------------------------------------------------
# solve (one variable) - required set/domain edge cases


CASES.extend(
    [
        case(
            "solve/quadratic-both-roots",
            "solve",
            solve_problem([rel("eq", power(sym("x"), 2), num(4))]),
            set_answer([num(-2), num(2)]),
            "correct",
            "x**2=4 has both real roots",
        ),
        case(
            "solve/quadratic-missing-root",
            "solve",
            solve_problem([rel("eq", power(sym("x"), 2), num(4))]),
            set_answer([num(-2)]),
            "incorrect",
            "the positive root is missing",
        ),
        case(
            "solve/quadratic-irrational-roots",
            "solve",
            solve_problem([rel("eq", power(sym("x"), 2), num(2))]),
            set_answer([neg(sqrt(num(2))), sqrt(num(2))]),
            "correct",
            "the exact roots are plus/minus sqrt(2)",
        ),
        case(
            "solve/inequality-open",
            "solve",
            solve_problem([rel("lt", power(sym("x"), 2), num(1))]),
            set_answer([], [interval(num(-1), num(1))]),
            "correct",
            "x**2<1 is the open interval (-1,1)",
        ),
        case(
            "solve/inequality-closed",
            "solve",
            solve_problem([rel("le", power(sym("x"), 2), num(1))]),
            set_answer(
                [],
                [interval(num(-1), num(1), lower_open=False, upper_open=False)],
            ),
            "correct",
            "x**2<=1 is the closed interval [-1,1]",
        ),
        case(
            "solve/inequality-mixed-endpoints",
            "solve",
            solve_problem([rel("lt", power(sym("x"), 2), num(1))]),
            set_answer(
                [],
                [interval(num(-1), num(1), lower_open=False, upper_open=False)],
            ),
            "incorrect",
            "the true endpoints are excluded",
        ),
        case(
            "solve/inequality-union-open",
            "solve",
            solve_problem([rel("gt", power(sym("x"), 2), num(1))]),
            set_answer(
                [],
                [interval(None, num(-1)), interval(num(1), None)],
            ),
            "correct",
            "x**2>1 is (-oo,-1) union (1,oo)",
        ),
        case(
            "solve/inequality-union-closed",
            "solve",
            solve_problem([rel("ge", power(sym("x"), 2), num(1))]),
            set_answer(
                [],
                [
                    interval(None, num(-1), upper_open=False),
                    interval(num(1), None, lower_open=False),
                ],
            ),
            "correct",
            "x**2>=1 keeps both endpoints",
        ),
        case(
            "solve/inequality-empty",
            "solve",
            solve_problem([rel("lt", power(sym("x"), 2), num(-1))]),
            set_answer([], []),
            "correct",
            "x**2<-1 has no real solutions",
        ),
        case(
            "solve/inequality-nonempty-answer-for-empty",
            "solve",
            solve_problem([rel("lt", power(sym("x"), 2), num(-1))]),
            set_answer([], [interval(num(-1), num(1))]),
            "incorrect",
            "the solution set is empty",
        ),
        case(
            "solve/all-reals",
            "solve",
            solve_problem([rel("eq", sym("x"), sym("x"))]),
            set_answer([], [interval(None, None)]),
            "correct",
            "an identity holds for every real",
        ),
        case(
            "solve/ne-open-holes",
            "solve",
            solve_problem([rel("ne", power(sym("x"), 2), num(1))]),
            set_answer(
                [],
                [
                    interval(None, num(-1)),
                    interval(num(-1), num(1)),
                    interval(num(1), None),
                ],
            ),
            "correct",
            "x**2!=1 removes the points x = -1 and x = 1",
        ),
        case(
            "solve/half-line",
            "solve",
            solve_problem([rel("gt", sym("x"), num(2))]),
            set_answer([], [interval(num(2), None)]),
            "correct",
            "x>2 is the open half-line (2,oo)",
        ),
        case(
            "solve/integer-domain-enumeration",
            "solve",
            solve_problem(
                [rel("le", power(sym("x"), 2), num(4))],
                symbols=[X_INT],
                domain="integer",
            ),
            set_answer([num(-2), num(-1), num(0), num(1), num(2)]),
            "correct",
            "x**2<=4 over the integers",
        ),
        case(
            "solve/integer-domain-missing-point",
            "solve",
            solve_problem(
                [rel("le", power(sym("x"), 2), num(4))],
                symbols=[X_INT],
                domain="integer",
            ),
            set_answer([num(-2), num(-1), num(0), num(1)]),
            "incorrect",
            "the integer 2 is missing",
        ),
        case(
            "solve/integer-domain-ne",
            "solve",
            solve_problem(
                [rel("ne", sym("x"), num(0))],
                symbols=[X_INT],
                domain="integer",
            ),
            set_answer([], [interval(None, num(0)), interval(num(0), None)]),
            "correct",
            "every integer except zero",
        ),
        case(
            "solve/rational-domain-irrational-equation",
            "solve",
            solve_problem(
                [rel("eq", power(sym("x"), 2), num(2))],
                symbols=[X_RAT],
                domain="rational",
            ),
            set_answer([], []),
            "correct",
            "x**2=2 has no rational roots",
        ),
        case(
            "solve/rational-domain-ne-irrational-exclusion",
            "solve",
            solve_problem(
                [rel("ne", power(sym("x"), 2), num(2))],
                symbols=[X_RAT],
                domain="rational",
            ),
            set_answer([], [interval(None, None)]),
            "correct",
            "every rational satisfies x**2!=2",
        ),
        case(
            "solve/extraneous-radical-root",
            "solve",
            solve_problem(
                [rel("eq", sqrt(sym("x")), sub(sym("x"), num(2)))],
            ),
            set_answer([num(4)]),
            "correct",
            "x=1 is extraneous for sqrt(x)=x-2",
        ),
        case(
            "solve/extraneous-radical-included",
            "solve",
            solve_problem(
                [rel("eq", sqrt(sym("x")), sub(sym("x"), num(2)))],
            ),
            set_answer([num(1), num(4)]),
            "incorrect",
            "x=1 does not satisfy the original radical equation",
        ),
        case(
            "solve/extraneous-rational-root",
            "solve",
            solve_problem(
                [
                    rel(
                        "eq",
                        div(sym("x"), sub(sym("x"), num(1))),
                        div(num(1), sub(sym("x"), num(1))),
                    )
                ],
            ),
            set_answer([], []),
            "correct",
            "x=1 is excluded by the denominator",
        ),
        case(
            "solve/extraneous-rational-included",
            "solve",
            solve_problem(
                [
                    rel(
                        "eq",
                        div(sym("x"), sub(sym("x"), num(1))),
                        div(num(1), sub(sym("x"), num(1))),
                    )
                ],
            ),
            set_answer([num(1)]),
            "incorrect",
            "the only algebraic root violates the source domain",
        ),
        case(
            "solve/absolute-value",
            "solve",
            solve_problem([rel("eq", absolute(sym("x")), num(2))]),
            set_answer([num(-2), num(2)]),
            "correct",
            "|x|=2 has two roots",
        ),
        case(
            "solve/absolute-value-no-solution",
            "solve",
            solve_problem([rel("eq", absolute(sym("x")), num(-1))]),
            set_answer([], []),
            "correct",
            "an absolute value is never negative",
        ),
        case(
            "solve/exponential",
            "solve",
            solve_problem([rel("eq", exp(sym("x")), num(1))]),
            set_answer([num(0)]),
            "correct",
            "exp(x)=1 has the unique root zero",
        ),
        case(
            "solve/exponential-no-real-solution",
            "solve",
            solve_problem([rel("eq", exp(sym("x")), num(-1))]),
            set_answer([], []),
            "correct",
            "exp is positive on the reals",
        ),
        case(
            "solve/logarithm",
            "solve",
            solve_problem([rel("eq", log(sym("x")), num(0))]),
            set_answer([num(1)]),
            "correct",
            "log(x)=0 has the unique root one",
        ),
        case(
            "solve/logarithm-empty-domain-intersection",
            "solve",
            solve_problem(
                [rel("eq", log(sym("x")), log(sub(sym("x"), num(1))))],
            ),
            set_answer([], []),
            "correct",
            "the translated logs never share a real argument",
        ),
        case(
            "solve/periodic-source-domain-refused",
            "solve",
            solve_problem(
                [rel("eq", log(sin(sym("x"))), log(sin(sym("x"))))],
            ),
            set_answer([], [interval(num(0), op("acos", num(-1)))]),
            "unknown",
            "the complete periodic source domain is not representable",
        ),
    ]
)


# ---------------------------------------------------------------------------
# solve-linear-system (unique ordered tuple)


CASES.extend(
    [
        case(
            "solve-linear-system/two-by-two",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(3)),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(2), num(1)]),
            "correct",
            "x+y=3, x-y=1 gives (2,1)",
        ),
        case(
            "solve-linear-system/two-by-two-wrong-order",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(3)),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(1), num(2)]),
            "incorrect",
            "the tuple is ordered (x,y)",
        ),
        case(
            "solve-linear-system/scaled-equations",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(mul(num(2), sym("x")), mul(num(3), sym("y"))),
                        num(7),
                    ),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(2), num(1)]),
            "correct",
            "2x+3y=7, x-y=1 gives (2,1)",
        ),
        case(
            "solve-linear-system/three-by-three",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(sym("x"), sym("y"), sym("z")),
                        num(6),
                    ),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                    rel("eq", sub(sym("y"), sym("z")), num(1)),
                ],
                solve_for=["x", "y", "z"],
                symbols=[X, Y, {"name": "z"}],
            ),
            tuple_answer([num(3), num(2), num(1)]),
            "correct",
            "the unique 3x3 solution is (3,2,1)",
        ),
        case(
            "solve-linear-system/three-by-three-wrong",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(sym("x"), sym("y"), sym("z")),
                        num(6),
                    ),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                    rel("eq", sub(sym("y"), sym("z")), num(1)),
                ],
                solve_for=["x", "y", "z"],
                symbols=[X, Y, {"name": "z"}],
            ),
            tuple_answer([num(1), num(2), num(3)]),
            "incorrect",
            "the components are permuted",
        ),
        case(
            "solve-linear-system/inconsistent-unsupported",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(1)),
                    rel("eq", add(sym("x"), sym("y")), num(2)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(0), num(0)]),
            "unsupported",
            "there is no unique solution",
        ),
        case(
            "solve-linear-system/underdetermined-unsupported",
            "solve-linear-system",
            solve_problem(
                [rel("eq", add(sym("x"), sym("y")), num(1))],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(1), num(0)]),
            "unsupported",
            "a single equation leaves a free parameter",
        ),
        case(
            "solve-linear-system/overdetermined-consistent",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(2)),
                    rel("eq", sub(sym("x"), sym("y")), num(0)),
                    rel("eq", mul(num(2), sym("x")), num(2)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(1), num(1)]),
            "correct",
            "redundant but consistent equations still have a unique tuple",
        ),
        case(
            "solve-linear-system/rational-solution",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(mul(num(2), sym("x")), mul(num(3), sym("y"))),
                        num(1),
                    ),
                    rel("eq", sub(sym("x"), sym("y")), num(2)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(Fraction(7, 5)), num(Fraction(-3, 5))]),
            "correct",
            "the unique solution is (7/5,-3/5)",
        ),
        case(
            "solve-linear-system/standard-order",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(sym("x"), mul(num(2), sym("y"))),
                        num(5),
                    ),
                    rel(
                        "eq",
                        sub(mul(num(3), sym("x")), sym("y")),
                        num(1),
                    ),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(1), num(2)]),
            "correct",
            "x+2y=5, 3x-y=1 gives (1,2)",
        ),
        case(
            "solve-linear-system/integer-domain",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(3)),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                ],
                solve_for=["x", "y"],
                symbols=[X_INT, {"name": "y", "domain": "integer"}],
                domain="integer",
            ),
            tuple_answer([num(2), num(1)]),
            "correct",
            "an integer solution satisfies the integer domain",
        ),
        case(
            "solve-linear-system/rational-domain",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(mul(num(2), sym("x")), mul(num(3), sym("y"))),
                        num(1),
                    ),
                    rel("eq", sub(sym("x"), sym("y")), num(2)),
                ],
                solve_for=["x", "y"],
                symbols=[X_RAT, {"name": "y", "domain": "rational"}],
                domain="rational",
            ),
            tuple_answer([num(Fraction(7, 5)), num(Fraction(-3, 5))]),
            "correct",
            "a rational solution satisfies the rational domain",
        ),
        case(
            "solve-linear-system/wrong-length",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(3)),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(2)]),
            "incorrect",
            "the candidate tuple must have two components",
        ),
        case(
            "solve-linear-system/nonlinear-unsupported",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", mul(sym("x"), sym("y")), num(1)),
                    rel("eq", add(sym("x"), sym("y")), num(2)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(1), num(1)]),
            "unsupported",
            "multi-symbol solving supports linear systems only",
        ),
        case(
            "solve-linear-system/inequality-unsupported",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(2)),
                    rel("gt", sym("x"), sym("y")),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            tuple_answer([num(2), num(0)]),
            "unsupported",
            "multi-symbol solving supports equalities only",
        ),
        case(
            "solve-linear-system/expression-answer-unsupported",
            "solve-linear-system",
            solve_problem(
                [
                    rel("eq", add(sym("x"), sym("y")), num(3)),
                    rel("eq", sub(sym("x"), sym("y")), num(1)),
                ],
                solve_for=["x", "y"],
                symbols=XY,
            ),
            expression_answer(num(2)),
            "unsupported",
            "a linear-system answer must be an ordered tuple",
        ),
        case(
            "solve-linear-system/singular-inconsistent",
            "solve-linear-system",
            solve_problem(
                [
                    rel(
                        "eq",
                        add(sym("x"), sym("y"), sym("z")),
                        num(1),
                    ),
                    rel(
                        "eq",
                        add(
                            mul(num(2), sym("x")),
                            mul(num(2), sym("y")),
                            mul(num(2), sym("z")),
                        ),
                        num(3),
                    ),
                    rel("eq", sub(sym("x"), sym("z")), num(0)),
                ],
                solve_for=["x", "y", "z"],
                symbols=[X, Y, {"name": "z"}],
            ),
            tuple_answer([num(1), num(0), num(1)]),
            "unsupported",
            "a contradictory dependent row leaves no solution",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Parametrised corpus runner


CASES_BY_ID = {case["id"]: case for case in CASES}


def _request(case: dict[str, object]) -> CorrectnessRequest:
    return CorrectnessRequest.model_validate(
        {"problem": case["problem"], "answer": case["answer"]}
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_corpus_case(case: dict[str, object]) -> None:
    result = check_in_process(_request(case))
    assert result.outcome == case["expected_outcome"], (
        f"{case['contract']}: {case['note']} | reason={result.reason!r} "
        f"| details={result.details!r}"
    )


def test_every_contract_has_at_least_ten_cases() -> None:
    counts: dict[str, int] = {}
    for case in CASES:
        contract = str(case["contract"])
        counts[contract] = counts.get(contract, 0) + 1
    required = {
        "antiderivative",
        "complete-square",
        "definite-integral",
        "differentiate",
        "expand",
        "factor",
        "determinant",
        "inverse",
        "lu",
        "matrix-multiply",
        "solve-linear-system",
    }
    assert required <= set(counts)
    for contract in sorted(required):
        assert counts[contract] >= 10, f"{contract} has only {counts[contract]} cases"
    assert len(CASES_BY_ID) == len(CASES), "case ids must be unique"
