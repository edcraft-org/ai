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

MAX_PROBLEM_DEGREE = 5
MAX_FACTOR_DEGREE = 2
MAX_PROBLEM_LITERAL = 20
MAX_EXPANDED_COEFFICIENT = 1_000
MAX_SYSTEM_ENTRY = 20
# Answer literals must cover every value the coefficient oracles can derive from
# the bounded problem scope: |4ac - b^2| <= 5,000,000 for complete-square and
# small rational roots for factor. The bound is deliberately explicit and is
# checked before any candidate reaches SymPy.
MAX_ANSWER_LITERAL = 10_000_000
MAX_RATIONAL_TEXT = 32
MAX_TREE_NODES = 80
MAX_TREE_DEPTH = 12

CONTRACT_SPECS = [
    {
        "contract_id": EXPAND,
        "kind": _KINDS[EXPAND],
        "title": "Expand and collect a polynomial",
        "summary": (
            "Equivalent collected polynomial with integer expanded coefficients, "
            "degree 1..5 and |coefficient| <= 1000. Like terms and hidden "
            "products must already be collected."
        ),
    },
    {
        "contract_id": FACTOR,
        "kind": _KINDS[FACTOR],
        "title": "Fully factor a linear or quadratic polynomial over the rationals",
        "summary": (
            "Equivalent product of explicit irreducible rational factors, degree "
            "1..2 and integer expanded coefficients with |coefficient| <= 1000. "
            "An unchanged expanded polynomial or an identity factor is not "
            "accepted; repeated roots and non-trivial scalar scalings are."
        ),
    },
    {
        "contract_id": SQUARE,
        "kind": _KINDS[SQUARE],
        "title": "Complete the square",
        "summary": (
            "Equivalent quadratic in a*(x-h)^2+k form, with a nonzero numeric "
            "scalar a and an explicit monic linear inner expression x-h. Degree "
            "exactly 2 and integer expanded coefficients |c| <= 1000; hidden "
            "nonlinear cancellations are not accepted."
        ),
    },
    {
        "contract_id": SYSTEM,
        "kind": _KINDS[SYSTEM],
        "title": "Solve a unique two-variable linear system",
        "summary": (
            "Complete ordered (x,y) tuple for a nonsingular exact 2 by 2 system "
            "with integer entries in [-20,20]. Singular and larger systems are "
            "outside this contract."
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
        coefficients = _coefficients(self.expression, literal_bound=MAX_PROBLEM_LITERAL)
        degree = len(coefficients) - 1
        limit = (
            MAX_PROBLEM_DEGREE
            if self.kind == "polynomial-expand"
            else MAX_FACTOR_DEGREE
        )
        if not 1 <= degree <= limit:
            raise ValueError("polynomial degree is outside this algebra contract")
        if self.kind == "polynomial-complete-square" and degree != 2:
            raise ValueError("completing the square requires a quadratic")
        if any(value.denominator != 1 for value in coefficients):
            raise ValueError("algebra contracts require integer expanded coefficients")
        if any(abs(value) > MAX_EXPANDED_COEFFICIENT for value in coefficients):
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
        if any(
            type(value) is not int or abs(value) > MAX_SYSTEM_ENTRY for value in entries
        ):
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


def _number(value: object, bound: int = MAX_ANSWER_LITERAL) -> Fraction:
    if not isinstance(value, str):
        raise ValueError("numeric leaves must be exact rational strings")
    if not value or value != value.strip():
        raise ValueError("numeric literals must not be empty or padded")
    if len(value) > MAX_RATIONAL_TEXT:
        raise ValueError("exact numeric literals are too long")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise ValueError("only finite exact rational literals are supported") from None
    if (
        abs(result.numerator) > bound
        or result.denominator > bound
        or result.denominator <= 0
    ):
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
    if len(left) + len(right) - 2 > MAX_PROBLEM_DEGREE:
        raise ValueError("polynomial degree exceeds five")
    values = [Fraction(0)] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            values[i + j] += a * b
    return _trim(values)


def _coefficients(
    expression: Expr, *, literal_bound: int = MAX_ANSWER_LITERAL
) -> tuple[Fraction, ...]:
    budget = [0]

    def visit(node: Expr, depth: int = 0) -> tuple[Fraction, ...]:
        budget[0] += 1
        if budget[0] > MAX_TREE_NODES or depth > MAX_TREE_DEPTH:
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
        if value == 0:
            return _x()
        if value < 0:
            return _op("add", _x(), _n(-value))
        return _op("sub", _x(), _n(value))

    base = (
        _op("pow", factor(first), _n(2))
        if first == second
        else _op("mul", factor(first), factor(second))
    )
    return base if a == 1 else _op("mul", _n(a), base)


def _completed(coefficients: tuple[Fraction, ...]) -> Expr:
    c, b, a = coefficients
    offset = b / (2 * a)
    if offset == 0:
        inner = _x()
    elif offset > 0:
        inner = _op("add", _x(), _n(offset))
    else:
        inner = _op("sub", _x(), _n(-offset))
    square = _op("pow", inner, _n(2))
    leading = square if a == 1 else _op("mul", _n(a), square)
    constant = c - b * b / (4 * a)
    return leading if constant == 0 else _op("add", leading, _n(constant))


def _integer_value(node: Expr, minimum: int, maximum: int) -> int | None:
    """Return an exact integer literal in the inclusive range, or ``None``."""
    if node.num is None:
        return None
    try:
        value = _number(node.num)
    except ValueError:
        return None
    if value.denominator != 1:
        return None
    integer = int(value)
    return integer if minimum <= integer <= maximum else None


def _is_number_literal(node: Expr) -> bool:
    if node.num is None:
        return False
    try:
        _number(node.num)
    except ValueError:
        return False
    return True


def _variable_monomial(node: Expr) -> int | None:
    """Degree of an explicit ``x`` or ``x^k`` (k >= 2) monomial."""
    if node.sym is not None:
        return 1 if node.sym == "x" else None
    if node.op == "pow" and len(node.args) == 2 and node.args[0].sym == "x":
        return _integer_value(node.args[1], 2, MAX_PROBLEM_DEGREE)
    return None


def _expanded_form(expression: Expr) -> bool:
    """A collected sum of distinct monomial terms, one explicit term each."""
    exponents: list[int] = []

    def term(node: Expr) -> bool:
        if node.op in {"add", "sub"}:
            return len(node.args) >= 2 and all(term(arg) for arg in node.args)
        if node.op == "mul":
            variables: list[int] = []
            constants: list[Expr] = []
            for arg in node.args:
                degree = _variable_monomial(arg)
                if degree is not None:
                    variables.append(degree)
                elif _is_number_literal(arg):
                    if _number(arg.num) == 0:
                        return False
                    constants.append(arg)
                else:
                    return False
            if len(variables) != 1 or len(constants) > 1:
                return False
            degree = variables[0]
        else:
            degree = _variable_monomial(node)
            if degree is None:
                if not _is_number_literal(node) or _number(node.num) == 0:
                    return False
                degree = 0
        exponents.append(degree)
        return True

    return term(expression) and len(exponents) == len(set(exponents))


def _collect_factors(expression: Expr) -> list[Expr]:
    """Flatten a product tree so scalar and repeated factors are counted once."""
    if expression.op != "mul":
        return [expression]
    factors: list[Expr] = []
    for arg in expression.args:
        factors.extend(_collect_factors(arg))
    return factors


def _factor_form(expression: Expr) -> bool:
    factors = _collect_factors(expression)
    if not factors:
        return False
    scalar_count = 0
    scalar_product = Fraction(1)
    polynomial_count = 0
    for factor in factors:
        coefficients = _coefficients(factor, literal_bound=MAX_ANSWER_LITERAL)
        if len(coefficients) == 1:
            if not _is_number_literal(factor):
                return False
            scalar_product *= _number(factor.num)
            scalar_count += 1
            continue
        polynomial_count += 1
        if factor.op == "pow":
            if len(factor.args) != 2:
                return False
            if _integer_value(factor.args[1], 2, MAX_PROBLEM_DEGREE) is None:
                return False
            base = factor.args[0]
            base_coefficients = _coefficients(base, literal_bound=MAX_ANSWER_LITERAL)
            if not _expanded_form(base) or not _irreducible(base_coefficients):
                return False
        elif not _expanded_form(factor) or not _irreducible(coefficients):
            return False
    if polynomial_count == 0 or scalar_product == 0:
        return False
    # Explicit unit scalars are identity-factor evasions; non-trivial products
    # of scalars are genuine alternative scalings.
    return not (scalar_count and scalar_product == 1)


def _linear_inner(inner: Expr) -> bool:
    """Accept only the explicit monic linear forms ``x`` or ``x +/- h``."""
    if inner.sym is not None:
        return inner.sym == "x"
    if inner.op not in {"add", "sub"} or len(inner.args) != 2:
        return False
    left, right = inner.args
    if inner.op == "sub":
        return left.sym == "x" and _is_number_literal(right)
    return (left.sym == "x" and _is_number_literal(right)) or (
        right.sym == "x" and _is_number_literal(left)
    )


def _square_form(expression: Expr) -> bool:
    if expression.op in {"add", "sub"}:
        terms = expression.args
        if len(terms) != 2 or not _is_number_literal(terms[1]):
            return False
    else:
        terms = [expression]
    square = terms[0]
    if square.op == "mul":
        if len(square.args) != 2 or not _is_number_literal(square.args[0]):
            return False
        if _number(square.args[0].num) == 0:
            return False
        square = square.args[1]
    if square.op != "pow" or len(square.args) != 2:
        return False
    if _integer_value(square.args[1], 2, 2) is None:
        return False
    return _linear_inner(square.args[0])


def validate_problem(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    if contract_id not in _KINDS:
        raise ValueError("unknown algebra contract")
    if not isinstance(problem, dict):
        raise ValueError("a problem must be a JSON object")
    if problem.get("kind") != _KINDS[contract_id]:
        raise ValueError("problem kind does not match the trusted algebra contract")
    model = LinearSystemProblem if contract_id == SYSTEM else AlgebraProblem
    return model.model_validate(problem).model_dump(mode="json", exclude_none=True)


def problem_extent(contract_id: str, problem: dict[str, Any]) -> dict[str, int | bool]:
    """Describe the actual polynomial or system, including cancellations."""
    validated = validate_problem(contract_id, problem)
    if contract_id == SYSTEM:
        entries = [value for row in validated["matrix"] for value in row]
        entries.extend(validated["rhs"])
        degree, dimension = 0, 2
        bound = max(abs(value) for value in entries)
    else:
        coefficients = _coefficients(Expr.model_validate(validated["expression"]))
        degree, dimension = len(coefficients) - 1, 0
        bound = max(abs(int(value)) for value in coefficients)
    return {
        "min_degree": degree,
        "max_degree": degree,
        "max_abs_coefficient": max(1, bound),
        "min_dimension": dimension,
        "max_dimension": dimension,
        "requires_general": False,
    }


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
    coefficients = _coefficients(
        Expr.model_validate(validated["expression"]),
        literal_bound=MAX_PROBLEM_LITERAL,
    )
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
        _coefficients(answer.expression, literal_bound=MAX_ANSWER_LITERAL)
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
        system_answer = SystemAnswer.model_validate(answer)
        values = [_number(value) for value in system_answer.values]
        return [
            {"values": [str(values[0] + offset), str(values[1])]}
            for offset in range(1, 7)
        ]
    ExpressionAnswer.model_validate(answer)
    coefficients = list(
        _coefficients(
            Expr.model_validate(validated["expression"]),
            literal_bound=MAX_PROBLEM_LITERAL,
        )
    )
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
    _coefficients(answer.expression, literal_bound=MAX_ANSWER_LITERAL)
    return _render_expr(answer.expression)


def boundary_problems(contract_id: str) -> list[dict[str, Any]]:
    if contract_id == SYSTEM:
        return [
            {"kind": _KINDS[SYSTEM], "matrix": [[2, 1], [1, -1]], "rhs": [5, 1]},
            {"kind": _KINDS[SYSTEM], "matrix": [[0, 2], [-3, 0]], "rhs": [1, -1]},
            {"kind": _KINDS[SYSTEM], "matrix": [[1, 0], [0, 1]], "rhs": [0, 0]},
            {"kind": _KINDS[SYSTEM], "matrix": [[2, 1], [1, 3]], "rhs": [1, 2]},
            {"kind": _KINDS[SYSTEM], "matrix": [[20, 1], [19, 1]], "rhs": [20, 19]},
        ]
    if contract_id not in _KINDS:
        raise ValueError("unknown algebra contract")
    polynomials = [
        (Fraction(-2), Fraction(0), Fraction(1)),  # x^2 - 2: irreducible
        (Fraction(1), Fraction(2), Fraction(1)),  # repeated root, zero offset
        (Fraction(1), Fraction(0), Fraction(1)),  # irreducible, zero linear term
        (Fraction(0), Fraction(0), Fraction(-2)),  # negative leading coefficient
        (Fraction(-1), Fraction(0), Fraction(2)),  # 2x^2 - 1
        (Fraction(-1), Fraction(0), Fraction(1)),  # difference of squares
    ]
    if contract_id != SQUARE:
        polynomials.append((Fraction(0), Fraction(3), Fraction(2)))  # 2x + 3
    expressions = [_expanded(values) for values in polynomials]
    if contract_id == EXPAND:
        expressions.append(
            _expanded(
                (
                    Fraction(1),
                    Fraction(0),
                    Fraction(0),
                    Fraction(0),
                    Fraction(0),
                    Fraction(1),
                )
            )
        )
        # The advertised coefficient limit is reachable through small literals.
        expressions.append(
            _op(
                "mul",
                _n(20),
                _n(20),
                _n(Fraction(5, 2)),
                _op("pow", _x(), _n(2)),
            )
        )
    if contract_id == SQUARE:
        # b = c = 1000 with a = 1; the oracle constant is -249000, which is
        # above the old implicit 100000 budget and must still be closed.
        expressions.append(
            _op(
                "add",
                _op("pow", _x(), _n(2)),
                _op("mul", _n(20), _n(20), _n(Fraction(5, 2)), _x()),
                _op("mul", _n(20), _n(20), _n(Fraction(5, 2))),
            )
        )
    return [
        {
            "kind": _KINDS[contract_id],
            "expression": expression.model_dump(mode="json", exclude_none=True),
        }
        for expression in expressions
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
        if contract_id == FACTOR:
            mode = draw(st.sampled_from(("random", "factored", "linear")))
            if mode == "linear":
                expression = _op(
                    "add",
                    _op(
                        "mul",
                        _n(draw(st.integers(-10, 10).filter(bool))),
                        _x(),
                    ),
                    _n(draw(st.integers(-10, 10))),
                )
            elif mode == "factored":
                # Build the product directly so input literals stay small while
                # expanded coefficients and repeated roots are exercised.
                leading = draw(st.integers(-5, 5).filter(bool))
                first = draw(st.integers(-10, 10))
                second = draw(st.integers(-10, 10))
                if first == second:
                    base = _op("pow", _op("sub", _x(), _n(first)), _n(2))
                else:
                    base = _op(
                        "mul",
                        _op("sub", _x(), _n(first)),
                        _op("sub", _x(), _n(second)),
                    )
                expression = base if leading == 1 else _op("mul", _n(leading), base)
            else:
                values = [
                    draw(st.integers(-10, 10)),
                    draw(st.integers(-10, 10)),
                    draw(st.integers(-10, 10).filter(bool)),
                ]
                expression = _expanded(tuple(Fraction(value) for value in values))
        else:
            degree = (
                draw(st.integers(1, MAX_PROBLEM_DEGREE)) if contract_id == EXPAND else 2
            )
            values = draw(
                st.lists(st.integers(-10, 10), min_size=degree, max_size=degree)
            )
            values.append(draw(st.integers(-10, 10).filter(bool)))
            expression = _expanded(tuple(Fraction(value) for value in values))
            if contract_id == EXPAND:
                expression = _op("mul", _n(2), expression)
        return {
            "kind": _KINDS[contract_id],
            "expression": expression.model_dump(mode="json", exclude_none=True),
        }

    return systems() if contract_id == SYSTEM else polynomials()
