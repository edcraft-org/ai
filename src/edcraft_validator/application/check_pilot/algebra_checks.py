"""Bounded algebra contracts with structural form and exact independent oracles.

The oracle performs coefficient and rational arithmetic. The execution checker
uses the safe Expr compiler and SymPy, retaining the submitted AST for form
requirements. No model-authored expression text is interpreted.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Literal

import sympy
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.domains.math.ir.compile import compile_expr
from edcraft_validator.domains.math.ir.schema import Expr

EXPAND = "polynomial.expand/1"
FACTOR = "polynomial.factor/1"
SQUARE = "polynomial.complete-square/1"
SYSTEM = "linear-system.unique/1"
_KINDS = {
    EXPAND: "polynomial-expand",
    FACTOR: "polynomial-factor",
    SQUARE: "polynomial-complete-square",
    SYSTEM: "linear-system-unique",
}
CONTRACT_SPECS = [
    {
        "contract_id": EXPAND,
        "kind": _KINDS[EXPAND],
        "title": "Expand and collect a polynomial",
        "summary": (
            "Equivalent polynomial in collected expanded form, degree at most five."
        ),
    },
    {
        "contract_id": FACTOR,
        "kind": _KINDS[FACTOR],
        "title": "Fully factor a quadratic over the rationals",
        "summary": (
            "Equivalent product of irreducible rational factors, degree one or two."
        ),
    },
    {
        "contract_id": SQUARE,
        "kind": _KINDS[SQUARE],
        "title": "Complete the square",
        "summary": (
            "Equivalent quadratic in a*(x-h)^2+k form, "
            "with monic inner linear expression."
        ),
    },
    {
        "contract_id": SYSTEM,
        "kind": _KINDS[SYSTEM],
        "title": "Solve a unique two-variable linear system",
        "summary": (
            "Complete ordered (x,y) tuple for a nonsingular exact 2 by 2 system."
        ),
    },
]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AlgebraProblem(_Closed):
    kind: Literal[
        "polynomial-expand", "polynomial-factor", "polynomial-complete-square"
    ]
    expression: Expr

    @model_validator(mode="after")
    def bounded_polynomial(self) -> AlgebraProblem:
        coefficients = _coefficients(self.expression, literal_bound=20)
        degree = len(coefficients) - 1
        if not 1 <= degree <= (5 if self.kind == "polynomial-expand" else 2):
            raise ValueError("polynomial degree is outside this algebra contract")
        if self.kind == "polynomial-complete-square" and degree != 2:
            raise ValueError("completing the square requires a quadratic")
        if any(abs(value) > 1000 for value in coefficients):
            raise ValueError("expanded coefficients exceed the bounded scope")
        return self


class LinearSystemProblem(_Closed):
    kind: Literal["linear-system-unique"]
    matrix: list[list[int]] = Field(min_length=2, max_length=2)
    rhs: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def bounded_unique_system(self) -> LinearSystemProblem:
        if any(len(row) != 2 for row in self.matrix):
            raise ValueError("the matrix must have exactly two rows and columns")
        entries = [value for row in self.matrix for value in row] + self.rhs
        if any(type(value) is not int or abs(value) > 20 for value in entries):
            raise ValueError("system coefficients must be integers in [-20,20]")
        a, b = self.matrix[0]
        c, d = self.matrix[1]
        if a * d == b * c:
            raise ValueError("only uniquely solvable systems are supported")
        return self


PROBLEM_TYPES = (AlgebraProblem, LinearSystemProblem)


class ExpressionAnswer(_Closed):
    expression: Expr


class SystemAnswer(_Closed):
    values: list[str] = Field(min_length=2, max_length=2)


def _number(value: str, bound: int = 100_000) -> Fraction:
    if len(value) > 32:
        raise ValueError("exact numeric literals are too long")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise ValueError("only finite exact rational literals are supported") from None
    if abs(result.numerator) > bound or result.denominator > bound:
        raise ValueError("rational literal exceeds the numeric budget")
    return result


def _trim(values: list[Fraction]) -> tuple[Fraction, ...]:
    if any(
        value.numerator.bit_length() > 128 or value.denominator.bit_length() > 128
        for value in values
    ):
        raise ValueError("polynomial expression exceeds the arithmetic budget")
    while len(values) > 1 and values[-1] == 0:
        values.pop()
    return tuple(values)


def _add(
    left: tuple[Fraction, ...], right: tuple[Fraction, ...]
) -> tuple[Fraction, ...]:
    values = [Fraction(0)] * max(len(left), len(right))
    for index, value in enumerate(left):
        values[index] += value
    for index, value in enumerate(right):
        values[index] += value
    return _trim(values)


def _multiply(
    left: tuple[Fraction, ...], right: tuple[Fraction, ...]
) -> tuple[Fraction, ...]:
    if len(left) + len(right) - 2 > 5:
        raise ValueError("polynomial degree exceeds five")
    values = [Fraction(0)] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            values[i + j] += a * b
    return _trim(values)


def _coefficients(
    expression: Expr, *, literal_bound: int = 100_000
) -> tuple[Fraction, ...]:
    budget = [0]

    def visit(node: Expr, depth: int = 0) -> tuple[Fraction, ...]:
        budget[0] += 1
        if budget[0] > 80 or depth > 12:
            raise ValueError("polynomial expression exceeds the tree budget")
        if node.num is not None:
            literal = _number(node.num)
            if abs(literal) > literal_bound:
                raise ValueError("numeric leaf exceeds the scope")
            return (literal,)
        if node.sym is not None:
            if node.sym != "x":
                raise ValueError("only the symbol x is supported")
            return (Fraction(0), Fraction(1))
        if node.param is not None:
            raise ValueError(
                "concrete polynomial expressions cannot contain parameters"
            )
        args = node.args
        if node.op in {"add", "mul"}:
            if not 2 <= len(args) <= 12:
                raise ValueError("sum/product requires 2..12 arguments")
            result: tuple[Fraction, ...] = (Fraction(0 if node.op == "add" else 1),)
            for arg in args:
                value = visit(arg, depth + 1)
                result = (
                    _add(result, value)
                    if node.op == "add"
                    else _multiply(result, value)
                )
            return result
        if node.op == "sub" and len(args) == 2:
            return _add(
                visit(args[0], depth + 1),
                tuple(-value for value in visit(args[1], depth + 1)),
            )
        if node.op == "pow" and len(args) == 2 and args[1].num is not None:
            exponent = _number(args[1].num)
            if exponent.denominator != 1 or not 0 <= exponent <= 5:
                raise ValueError("polynomial powers must be integers from zero to five")
            base = visit(args[0], depth + 1)
            result = (Fraction(1),)
            for _ in range(int(exponent)):
                result = _multiply(result, base)
            return result
        raise ValueError("unsupported polynomial operator or arity")

    return visit(expression)


def _n(value: Fraction | int) -> Expr:
    return Expr(num=str(value))


def _x() -> Expr:
    return Expr(sym="x")


def _op(name: str, *args: Expr) -> Expr:
    return Expr(op=name, args=list(args))


def _expanded(coefficients: tuple[Fraction, ...]) -> Expr:
    terms = []
    for degree in range(len(coefficients) - 1, -1, -1):
        value = coefficients[degree]
        if not value:
            continue
        if degree == 0:
            term = _n(value)
        else:
            power = _x() if degree == 1 else _op("pow", _x(), _n(degree))
            term = power if value == 1 else _op("mul", _n(value), power)
        terms.append(term)
    return _op("add", *terms) if len(terms) > 1 else terms[0] if terms else _n(0)


def _square_root(value: Fraction) -> Fraction | None:
    if value < 0:
        return None
    numerator, denominator = math.isqrt(value.numerator), math.isqrt(value.denominator)
    if (
        numerator * numerator != value.numerator
        or denominator * denominator != value.denominator
    ):
        return None
    return Fraction(numerator, denominator)


def _irreducible(coefficients: tuple[Fraction, ...]) -> bool:
    if len(coefficients) == 2:
        return True
    if len(coefficients) != 3:
        return False
    c, b, a = coefficients
    return _square_root(b * b - 4 * a * c) is None


def _factored(coefficients: tuple[Fraction, ...]) -> Expr:
    if len(coefficients) != 3 or _irreducible(coefficients):
        return _expanded(coefficients)
    c, b, a = coefficients
    root = _square_root(b * b - 4 * a * c)
    assert root is not None
    first, second = (-b + root) / (2 * a), (-b - root) / (2 * a)

    def factor(value: Fraction) -> Expr:
        return _x() if value == 0 else _op("sub", _x(), _n(value))

    base = (
        _op("pow", factor(first), _n(2))
        if first == second
        else _op("mul", factor(first), factor(second))
    )
    return base if a == 1 else _op("mul", _n(a), base)


def _completed(coefficients: tuple[Fraction, ...]) -> Expr:
    c, b, a = coefficients
    offset = b / (2 * a)
    inner = _x() if not offset else _op("add", _x(), _n(offset))
    square = _op("pow", inner, _n(2))
    leading = square if a == 1 else _op("mul", _n(a), square)
    constant = c - b * b / (4 * a)
    return _op("add", leading, _n(constant))


def _expanded_form(expression: Expr) -> bool:
    exponents: list[int] = []

    def term(node: Expr) -> bool:
        if node.op in {"add", "sub"}:
            return bool(node.args) and all(term(arg) for arg in node.args)
        coefficients = _coefficients(node)
        nonzero = [index for index, value in enumerate(coefficients) if value]
        if len(nonzero) != 1:
            return False
        if node.op == "mul":
            variables = [arg for arg in node.args if len(_coefficients(arg)) > 1]
            constants = [arg for arg in node.args if len(_coefficients(arg)) == 1]
            if (
                len(variables) != 1
                or len(constants) > 1
                or any(arg.num is None for arg in constants)
            ):
                return False
            base = variables[0]
        else:
            base = node
        if base.op is not None and not (base.op == "pow" and base.args[0].sym == "x"):
            return False
        exponents.append(nonzero[0])
        return True

    return term(expression) and len(exponents) == len(set(exponents))


def _factor_form(expression: Expr) -> bool:
    factors = expression.args if expression.op == "mul" else [expression]
    scalar_count = 0
    for factor in factors:
        if factor.op == "mul":
            if not _factor_form(factor):
                return False
            continue
        coefficients = _coefficients(factor)
        if len(coefficients) == 1:
            scalar_count += 1
            if coefficients[0] in {0, 1} or factor.num is None:
                return False
        elif factor.op == "pow":
            exponent = _number(factor.args[1].num or "0")
            if (
                exponent.denominator != 1
                or not 2 <= exponent <= 5
                or not _irreducible(_coefficients(factor.args[0]))
            ):
                return False
        elif not _irreducible(coefficients):
            return False
    return scalar_count <= 1


def _square_form(expression: Expr) -> bool:
    terms = expression.args if expression.op in {"add", "sub"} else [expression]
    if len(terms) > 2:
        return False
    square = terms[0]
    if len(terms) == 2 and terms[1].num is None:
        return False
    if square.op == "mul":
        if (
            len(square.args) != 2
            or square.args[0].num is None
            or _number(square.args[0].num) == 0
        ):
            return False
        square = square.args[1]
    if square.op != "pow" or len(square.args) != 2 or square.args[1].num != "2":
        return False
    inner = _coefficients(square.args[0])
    return len(inner) == 2 and inner[1] == 1


def validate_problem(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    if contract_id not in _KINDS or problem.get("kind") != _KINDS[contract_id]:
        raise ValueError("problem kind does not match the trusted algebra contract")
    model = LinearSystemProblem if contract_id == SYSTEM else AlgebraProblem
    return model.model_validate(problem).model_dump(mode="json", exclude_none=True)


def expected_answer(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    validated = validate_problem(contract_id, problem)
    if contract_id == SYSTEM:
        a, b = validated["matrix"][0]
        c, d = validated["matrix"][1]
        e, f = validated["rhs"]
        determinant = a * d - b * c
        return {
            "values": [
                str(Fraction(e * d - b * f, determinant)),
                str(Fraction(a * f - e * c, determinant)),
            ]
        }
    coefficients = _coefficients(Expr.model_validate(validated["expression"]))
    expression = (
        _expanded(coefficients)
        if contract_id == EXPAND
        else _factored(coefficients)
        if contract_id == FACTOR
        else _completed(coefficients)
    )
    return {"expression": expression.model_dump(mode="json", exclude_none=True)}


def check_answer(
    contract_id: str, problem: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    validated = validate_problem(contract_id, problem)
    try:
        if contract_id == SYSTEM:
            system_answer = SystemAnswer.model_validate(candidate)
            values = [_number(value) for value in system_answer.values]
            matrix = sympy.Matrix(validated["matrix"])
            vector = sympy.Matrix(
                [sympy.Rational(value.numerator, value.denominator) for value in values]
            )
            return matrix * vector == sympy.Matrix(validated["rhs"])
        answer = ExpressionAnswer.model_validate(candidate)
        _coefficients(answer.expression)
        form = (
            _expanded_form
            if contract_id == EXPAND
            else _factor_form
            if contract_id == FACTOR
            else _square_form
        )
        if not form(answer.expression):
            return False
        symbols = {"x": sympy.Symbol("x", real=True)}
        source = compile_expr(Expr.model_validate(validated["expression"]), symbols)
        actual = compile_expr(answer.expression, symbols)
        return sympy.Poly(source - actual, symbols["x"]).is_zero is True
    except (ValueError, TypeError, KeyError, IndexError, sympy.PolynomialError):
        return False


def wrong_answers(
    contract_id: str, problem: dict[str, Any], answer: dict[str, Any]
) -> list[dict[str, Any]]:
    validated = validate_problem(contract_id, problem)
    if contract_id == SYSTEM:
        values = [_number(value) for value in answer["values"]]
        return [
            {"values": [str(values[0] + offset), str(values[1])]}
            for offset in range(1, 7)
        ]
    coefficients = list(_coefficients(Expr.model_validate(validated["expression"])))
    candidates = []
    for offset in range(1, 7):
        shifted = tuple([coefficients[0] + offset, *coefficients[1:]])
        expression = (
            _expanded(shifted)
            if contract_id == EXPAND
            else _factored(shifted)
            if contract_id == FACTOR
            else _completed(shifted)
        )
        candidates.append(
            {"expression": expression.model_dump(mode="json", exclude_none=True)}
        )
    return candidates


def render_problem(contract_id: str, problem: dict[str, Any]) -> str:
    validated = validate_problem(contract_id, problem)
    if contract_id == SYSTEM:
        rows = [
            f"{row[0]}*x + ({row[1]})*y = {rhs}"
            for row, rhs in zip(validated["matrix"], validated["rhs"], strict=True)
        ]
        return "Solve for the ordered pair (x, y): " + "; ".join(rows)
    expression = _render_expr(Expr.model_validate(validated["expression"]))
    request = {
        EXPAND: "Expand and collect like terms",
        FACTOR: "Fully factorise over the rational numbers",
        SQUARE: "Write in completed-square form a*(x-h)^2+k",
    }[contract_id]
    return f"{request}: {expression}"


def _render_expr(expression: Expr) -> str:
    if expression.num is not None:
        return expression.num
    if expression.sym is not None:
        return expression.sym
    operator = {"add": " + ", "sub": " - ", "mul": " * ", "pow": " ^ "}[
        expression.op or ""
    ]
    return "(" + operator.join(_render_expr(arg) for arg in expression.args) + ")"


def render_answer(contract_id: str, candidate: dict[str, Any]) -> str:
    if contract_id == SYSTEM:
        system_answer = SystemAnswer.model_validate(candidate)
        return (
            "(" + ", ".join(str(_number(value)) for value in system_answer.values) + ")"
        )
    answer = ExpressionAnswer.model_validate(candidate)
    _coefficients(answer.expression)
    return _render_expr(answer.expression)


def boundary_problems(contract_id: str) -> list[dict[str, Any]]:
    if contract_id == SYSTEM:
        return [
            {"kind": _KINDS[SYSTEM], "matrix": [[2, 1], [1, -1]], "rhs": [5, 1]},
            {"kind": _KINDS[SYSTEM], "matrix": [[0, 2], [-3, 0]], "rhs": [1, -1]},
            {"kind": _KINDS[SYSTEM], "matrix": [[1, 0], [0, 1]], "rhs": [0, 0]},
        ]
    if contract_id not in _KINDS:
        raise ValueError("unknown algebra contract")
    polynomials = [
        (Fraction(-1), Fraction(0), Fraction(1)),
        (Fraction(1), Fraction(2), Fraction(1)),
        (Fraction(1), Fraction(0), Fraction(1)),
        (Fraction(0), Fraction(0), Fraction(-2)),
    ]
    return [
        {
            "kind": _KINDS[contract_id],
            "expression": _expanded(values).model_dump(mode="json", exclude_none=True),
        }
        for values in polynomials
    ]


def problem_strategy(contract_id: str) -> st.SearchStrategy[dict[str, Any]]:
    if contract_id not in _KINDS:
        raise ValueError("unknown algebra contract")

    @st.composite
    def systems(draw: st.DrawFn) -> dict[str, Any]:
        matrix = draw(
            st.lists(
                st.lists(st.integers(-5, 5), min_size=2, max_size=2),
                min_size=2,
                max_size=2,
            ).filter(lambda rows: rows[0][0] * rows[1][1] != rows[0][1] * rows[1][0])
        )
        return {
            "kind": _KINDS[SYSTEM],
            "matrix": matrix,
            "rhs": draw(st.lists(st.integers(-20, 20), min_size=2, max_size=2)),
        }

    @st.composite
    def polynomials(draw: st.DrawFn) -> dict[str, Any]:
        degree = (
            draw(st.integers(1, 5 if contract_id == EXPAND else 2))
            if contract_id != SQUARE
            else 2
        )
        values = draw(st.lists(st.integers(-10, 10), min_size=degree, max_size=degree))
        values.append(draw(st.integers(-10, 10).filter(bool)))
        expression = _expanded(tuple(Fraction(value) for value in values))
        if contract_id == EXPAND:
            expression = _op("mul", _n(2), expression)
        return {
            "kind": _KINDS[contract_id],
            "expression": expression.model_dump(mode="json", exclude_none=True),
        }

    return systems() if contract_id == SYSTEM else polynomials()
