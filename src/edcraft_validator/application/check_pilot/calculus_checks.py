"""Trusted calculus check kernel for the reusable-check pilot.

The module owns three developer-authored contracts:

* ``polynomial.antiderivative/1``
* ``polynomial.definite-integral/1``
* ``expression.differentiate/1``

Every problem is closed, bounded data. Candidate expressions are the shared
:class:`~edcraft_validator.domains.math.ir.schema.Expr` tree; no string is ever
parsed or evaluated. The independent ``expected_answer`` oracle uses exact
``Fraction`` arithmetic and a recursive derivative rule engine, never
``sympy.diff``. ``check_answer`` may use SymPy only after the closed tree has
been compiled, and symbolic equality (not sampled numerical equality) decides
candidate equivalence.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Literal

import sympy
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
)
from edcraft_validator.domains.math.ir.schema import Expr, SymbolSpec

MAX_DEGREE = 5
MAX_ANTIDERIVATIVE_DEGREE = MAX_DEGREE + 1
MAX_ABS_COEFFICIENT = 10_000
MAX_DENOMINATOR = 1_000
MAX_ANSWER_ABS = 10**60
MAX_ANSWER_DENOMINATOR = 10**60
MAX_BOUND = 1_000
MAX_EXPRESSION_NODES = 120
MAX_EXPRESSION_DEPTH = 16
MAX_SYMBOLS = 4
MAX_POWER = 12
MAX_RATIONAL_TEXT = 200
MAX_ARITHMETIC_BITS = 256

ANTIDERIVATIVE_CONTRACT = "polynomial.antiderivative/1"
DEFINITE_INTEGRAL_CONTRACT = "polynomial.definite-integral/1"
DIFFERENTIATE_CONTRACT = "expression.differentiate/1"

CONTRACT_SPECS: list[dict[str, str]] = [
    {
        "contract_id": ANTIDERIVATIVE_CONTRACT,
        "title": "Antiderivative of a bounded polynomial",
        "summary": (
            "Find a primitive of a degree-at-most-5 exact rational polynomial. "
            "One-primitive requests accept any valid primitive; general requests "
            "require the +C family marker, with any additive constant accepted."
        ),
        "kind": "polynomial_antiderivative",
    },
    {
        "contract_id": DEFINITE_INTEGRAL_CONTRACT,
        "title": "Definite integral of a bounded polynomial",
        "summary": (
            "Evaluate an exact degree-at-most-5 polynomial integral between "
            "finite rational bounds, including reversed and equal bounds."
        ),
        "kind": "polynomial_definite_integral",
    },
    {
        "contract_id": DIFFERENTIATE_CONTRACT,
        "title": "First derivative of a bounded closed expression",
        "summary": (
            "Differentiate bounded arithmetic expressions with sin/cos/exp/log, "
            "product, chain and quotient rules only when the real domain can be "
            "conservatively validated; unsupported or undecidable cases fail."
        ),
        "kind": "expression_differentiate",
    },
]
_SPEC_INDEX = {spec["contract_id"]: spec for spec in CONTRACT_SPECS}


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False
    )


def _parse_rational(
    text: object,
    *,
    label: str,
    max_abs: int = MAX_ABS_COEFFICIENT,
    max_denominator: int = MAX_DENOMINATOR,
) -> Fraction:
    if not isinstance(text, str):
        raise ValueError(f"{label} must be an exact rational string")
    if not text or len(text) > MAX_RATIONAL_TEXT:
        raise ValueError(f"{label} is empty or too long")
    if text != text.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label} is not an exact finite rational") from exc
    if value.denominator > max_denominator:
        raise ValueError(f"{label} denominator is out of bounds")
    if abs(value.numerator) > max_abs:
        raise ValueError(f"{label} is out of bounds")
    return value


def _canonical_rational_list(
    values: object,
    *,
    label: str,
    max_length: int,
    max_abs: int = MAX_ABS_COEFFICIENT,
    max_denominator: int = MAX_DENOMINATOR,
) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be a list")
    if not 1 <= len(values) <= max_length:
        raise ValueError(f"{label} must contain between 1 and {max_length} entries")
    parsed = [
        _parse_rational(
            entry,
            label=f"{label}[{index}]",
            max_abs=max_abs,
            max_denominator=max_denominator,
        )
        for index, entry in enumerate(values)
    ]
    while len(parsed) > 1 and parsed[-1] == 0:
        parsed.pop()
    return [str(value) for value in parsed]


class PolynomialAntiderivativeProblem(_ClosedModel):
    kind: Literal["polynomial_antiderivative"] = "polynomial_antiderivative"
    coefficients: list[str] = Field(min_length=1, max_length=MAX_DEGREE + 1)
    general: bool
    variable: Literal["x"] = "x"

    @field_validator("coefficients", mode="before")
    @classmethod
    def _bounded_coefficients(cls, value: object) -> list[str]:
        return _canonical_rational_list(
            value,
            label="coefficients",
            max_length=MAX_DEGREE + 1,
        )


class PolynomialAntiderivativeAnswer(_ClosedModel):
    kind: Literal["polynomial_antiderivative_answer"] = (
        "polynomial_antiderivative_answer"
    )
    coefficients: list[str] = Field(
        min_length=1, max_length=MAX_ANTIDERIVATIVE_DEGREE + 1
    )
    general: bool

    @field_validator("coefficients", mode="before")
    @classmethod
    def _bounded_coefficients(cls, value: object) -> list[str]:
        return _canonical_rational_list(
            value,
            label="coefficients",
            max_length=MAX_ANTIDERIVATIVE_DEGREE + 1,
            max_abs=MAX_ANSWER_ABS,
            max_denominator=MAX_ANSWER_DENOMINATOR,
        )


class PolynomialDefiniteIntegralProblem(_ClosedModel):
    kind: Literal["polynomial_definite_integral"] = "polynomial_definite_integral"
    coefficients: list[str] = Field(min_length=1, max_length=MAX_DEGREE + 1)
    lower: str
    upper: str
    variable: Literal["x"] = "x"

    @field_validator("coefficients", mode="before")
    @classmethod
    def _bounded_coefficients(cls, value: object) -> list[str]:
        return _canonical_rational_list(
            value,
            label="coefficients",
            max_length=MAX_DEGREE + 1,
        )

    @field_validator("lower", "upper", mode="before")
    @classmethod
    def _bounded_bound(cls, value: object) -> str:
        return str(_parse_rational(value, label="bound", max_abs=MAX_BOUND))


class PolynomialDefiniteIntegralAnswer(_ClosedModel):
    kind: Literal["polynomial_definite_integral_answer"] = (
        "polynomial_definite_integral_answer"
    )
    value: str

    @field_validator("value", mode="before")
    @classmethod
    def _bounded_value(cls, value: object) -> str:
        return str(
            _parse_rational(
                value,
                label="value",
                max_abs=MAX_ANSWER_ABS,
                max_denominator=MAX_ANSWER_DENOMINATOR,
            )
        )


class ExpressionSymbol(_ClosedModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    positive: bool = False
    nonzero: bool = False


class ExpressionDifferentiateProblem(_ClosedModel):
    kind: Literal["expression_differentiate"] = "expression_differentiate"
    expression: Expr
    symbols: list[ExpressionSymbol] = Field(min_length=1, max_length=MAX_SYMBOLS)
    variable: Literal["x"] = "x"


class ExpressionDifferentiateAnswer(_ClosedModel):
    kind: Literal["expression_differentiate_answer"] = "expression_differentiate_answer"
    expression: Expr


PROBLEM_TYPES: tuple[type[BaseModel], ...] = (
    PolynomialAntiderivativeProblem,
    PolynomialDefiniteIntegralProblem,
    ExpressionDifferentiateProblem,
)
_PROBLEM_MODELS: dict[str, type[BaseModel]] = {
    ANTIDERIVATIVE_CONTRACT: PolynomialAntiderivativeProblem,
    DEFINITE_INTEGRAL_CONTRACT: PolynomialDefiniteIntegralProblem,
    DIFFERENTIATE_CONTRACT: ExpressionDifferentiateProblem,
}

_SUPPORTED_OPS = frozenset(
    {"add", "mul", "sub", "div", "pow", "sin", "cos", "exp", "log"}
)
_ARITY = {
    "sub": 2,
    "div": 2,
    "pow": 2,
    "sin": 1,
    "cos": 1,
    "exp": 1,
    "log": 1,
}


def _expr_dump(expr: Expr) -> dict[str, Any]:
    """Dump a closed tree without None scaffolding, preserving its structure."""
    return expr.model_dump(mode="json", exclude_defaults=True)


def _problem_dump(parsed: BaseModel) -> dict[str, Any]:
    data = parsed.model_dump(mode="json")
    if isinstance(parsed, ExpressionDifferentiateProblem):
        data["expression"] = _expr_dump(parsed.expression)
    return data


def _descriptor(contract_id: object) -> dict[str, str]:
    if not isinstance(contract_id, str):
        raise ValueError("contract id must be a string")
    try:
        return _SPEC_INDEX[contract_id]
    except KeyError as exc:
        raise ValueError(f"unknown calculus contract {contract_id!r}") from exc


def _walk(expr: Expr, depth: int = 0) -> int:
    if depth > MAX_EXPRESSION_DEPTH:
        raise ValueError("expression nesting is too deep")
    if expr.param is not None:
        raise ValueError("unbound parameter nodes are unsupported")
    if expr.op is None:
        if expr.num is not None:
            _parse_rational(expr.num, label="numeric literal")
        return 1
    if expr.op not in _SUPPORTED_OPS:
        raise ValueError(f"unsupported operation {expr.op!r}")
    expected = _ARITY.get(expr.op)
    if expected is not None:
        if len(expr.args) != expected:
            raise ValueError(f"{expr.op} requires {expected} arguments")
    elif not expr.args:
        raise ValueError(f"{expr.op} requires at least one argument")
    count = 1
    for child in expr.args:
        count += _walk(child, depth + 1)
        if count > MAX_EXPRESSION_NODES:
            raise ValueError("expression has too many nodes")
    return count


def _integer_exponent(expr: Expr) -> int:
    if expr.num is None:
        raise ValueError("powers require an exact integer exponent")
    value = _parse_rational(expr.num, label="exponent", max_abs=MAX_POWER)
    if value.denominator != 1:
        raise ValueError("powers require an integer exponent")
    return int(value)


def _expr_symbols(expr: Expr) -> set[str]:
    if expr.sym is not None:
        return {expr.sym}
    found: set[str] = set()
    for child in expr.args:
        found.update(_expr_symbols(child))
    return found


def _sign_facts(
    expr: Expr, assumptions: dict[str, ExpressionSymbol]
) -> tuple[int | None, bool]:
    """Conservative sign and non-zero facts for domain validation."""
    if expr.num is not None:
        value = _parse_rational(expr.num, label="literal")
        return (0 if value == 0 else (1 if value > 0 else -1), value != 0)
    if expr.sym is not None:
        symbol = assumptions[expr.sym]
        if symbol.positive:
            return (1, True)
        return (None, symbol.nonzero)
    op = expr.op
    assert op is not None
    if op == "add":
        signs = [_sign_facts(child, assumptions) for child in expr.args]
        if all(value_sign == 1 for value_sign, _ in signs):
            return (1, True)
        if all(value_sign == -1 for value_sign, _ in signs):
            return (-1, True)
        return (None, False)
    if op == "sub":
        left, right = (_sign_facts(child, assumptions) for child in expr.args)
        if left[0] is not None and right[0] is not None:
            difference = left[0] - right[0]
            return (
                0 if difference == 0 else (1 if difference > 0 else -1),
                difference != 0,
            )
        return (None, False)
    if op == "mul":
        facts = [_sign_facts(child, assumptions) for child in expr.args]
        if any(value_sign == 0 for value_sign, _ in facts):
            return (0, False)
        product: int | None = 1
        for value_sign, _ in facts:
            if value_sign is None:
                product = None
            elif product is not None:
                product *= value_sign
        return (product, all(nonzero for _, nonzero in facts))
    if op == "div":
        numerator, denominator = (
            _sign_facts(child, assumptions) for child in expr.args
        )
        if denominator[0] == 0 or not denominator[1]:
            return (None, False)
        quotient_sign: int | None = None
        if numerator[0] is not None and denominator[0] is not None:
            quotient_sign = numerator[0] * denominator[0]
        return (quotient_sign, numerator[1] and denominator[1])
    if op == "pow":
        base = _sign_facts(expr.args[0], assumptions)
        exponent = _integer_exponent(expr.args[1])
        if exponent == 0:
            return (1, True)
        if exponent < 0:
            if not base[1]:
                return (None, False)
            negative_sign = None if base[0] is None else base[0] ** abs(exponent)
            return (negative_sign, True)
        if base[0] == 0:
            return (0, False)
        if exponent % 2 == 0:
            return (1, True) if base[1] else (None, False)
        power_sign = None if base[0] is None else base[0] ** exponent
        return (power_sign, base[1])
    if op == "exp":
        return (1, True)
    if op in {"sin", "cos", "log"}:
        return (None, False)
    raise ValueError(f"unsupported operation {op!r}")


def _validate_domain(expr: Expr, assumptions: dict[str, ExpressionSymbol]) -> None:
    op = expr.op
    if op is None:
        return
    if op == "log":
        sign, _ = _sign_facts(expr.args[0], assumptions)
        if sign != 1:
            raise ValueError("log requires a provably positive argument")
    if op == "div":
        _, nonzero = _sign_facts(expr.args[1], assumptions)
        if not nonzero:
            raise ValueError("division requires a provably non-zero denominator")
    if op == "pow":
        exponent = _integer_exponent(expr.args[1])
        if exponent < 0:
            _, nonzero = _sign_facts(expr.args[0], assumptions)
            if not nonzero:
                raise ValueError("negative powers require a provably non-zero base")
    for child in expr.args:
        _validate_domain(child, assumptions)


def _validate_differentiate(problem: ExpressionDifferentiateProblem) -> None:
    names = [symbol.name for symbol in problem.symbols]
    if len(names) != len(set(names)):
        raise ValueError("symbol declarations must be unique")
    if problem.variable not in names:
        raise ValueError("the differentiation variable must be declared")
    assumptions = {symbol.name: symbol for symbol in problem.symbols}
    used = _expr_symbols(problem.expression)
    unknown = sorted(used - set(names))
    if unknown:
        raise ValueError("expression references undeclared symbols")
    _walk(problem.expression)
    _validate_domain(problem.expression, assumptions)
    # Reject a within-node-budget problem whose derivative would exceed the
    # closed answer budget; an accepted problem must always have a valid
    # expected answer.
    _walk(_differentiate(problem.expression, problem.variable))


def validate_problem(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    descriptor = _descriptor(contract_id)
    if not isinstance(problem, dict):
        raise ValueError("a problem must be a JSON-compatible object")
    if problem.get("kind") != descriptor["kind"]:
        raise ValueError(
            f"problem kind must be {descriptor['kind']!r} for {contract_id}"
        )
    model = _PROBLEM_MODELS[contract_id]
    try:
        parsed = model.model_validate(problem)
    except ValidationError as exc:
        raise ValueError(f"invalid problem: {exc}") from exc
    if isinstance(parsed, ExpressionDifferentiateProblem):
        _validate_differentiate(parsed)
    return _problem_dump(parsed)


def _parse_coefficients(problem: dict[str, Any]) -> list[Fraction]:
    return [Fraction(value) for value in problem["coefficients"]]


def _integral_coefficients(coefficients: list[Fraction]) -> list[Fraction]:
    result = [Fraction(0)]
    for exponent, coefficient in enumerate(coefficients, start=1):
        result.append(coefficient / exponent)
    while len(result) > 1 and result[-1] == 0:
        result.pop()
    return result


def _evaluate_polynomial(coefficients: list[Fraction], point: Fraction) -> Fraction:
    value = Fraction(0)
    for coefficient in reversed(coefficients):
        value = value * point + coefficient
    return value


def _antiderivative_answer(problem: dict[str, Any]) -> dict[str, Any]:
    coefficients = _parse_coefficients(problem)
    integral = _integral_coefficients(coefficients)
    return {
        "kind": "polynomial_antiderivative_answer",
        "coefficients": [str(value) for value in integral],
        "general": bool(problem["general"]),
    }


def _definite_integral_answer(problem: dict[str, Any]) -> dict[str, Any]:
    coefficients = _parse_coefficients(problem)
    integral = _integral_coefficients(coefficients)
    lower = _parse_rational(problem["lower"], label="lower", max_abs=MAX_BOUND)
    upper = _parse_rational(problem["upper"], label="upper", max_abs=MAX_BOUND)
    value = _evaluate_polynomial(integral, upper) - _evaluate_polynomial(
        integral, lower
    )
    return {
        "kind": "polynomial_definite_integral_answer",
        "value": str(value),
    }


def _definite_integral_termwise(problem: dict[str, Any]) -> Fraction:
    """Checker quadrature: per-term exact power differences, no antiderivative."""
    coefficients = _parse_coefficients(problem)
    lower = _parse_rational(problem["lower"], label="lower", max_abs=MAX_BOUND)
    upper = _parse_rational(problem["upper"], label="upper", max_abs=MAX_BOUND)
    total = Fraction(0)
    for exponent, coefficient in enumerate(coefficients):
        power = exponent + 1
        total += coefficient * (upper**power - lower**power) / power
    return total


def expected_answer(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    validated = validate_problem(contract_id, problem)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        return _antiderivative_answer(validated)
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        return _definite_integral_answer(validated)
    if contract_id == DIFFERENTIATE_CONTRACT:
        parsed = ExpressionDifferentiateProblem.model_validate(validated)
        derivative = _differentiate(parsed.expression, parsed.variable)
        _walk(derivative)
        return {
            "kind": "expression_differentiate_answer",
            "expression": _expr_dump(derivative),
        }
    raise ValueError(f"unknown calculus contract {contract_id!r}")


def _answer_model(contract_id: str, candidate: object) -> BaseModel:
    if not isinstance(candidate, dict):
        raise ValueError("a candidate answer must be a JSON-compatible object")
    models: dict[str, type[BaseModel]] = {
        ANTIDERIVATIVE_CONTRACT: PolynomialAntiderivativeAnswer,
        DEFINITE_INTEGRAL_CONTRACT: PolynomialDefiniteIntegralAnswer,
        DIFFERENTIATE_CONTRACT: ExpressionDifferentiateAnswer,
    }
    try:
        return models[contract_id].model_validate(candidate)
    except ValidationError as exc:
        raise ValueError(f"invalid candidate answer: {exc}") from exc


def _check_antiderivative(
    problem: dict[str, Any], candidate: PolynomialAntiderivativeAnswer
) -> bool:
    if candidate.general != problem["general"]:
        return False
    answer = [Fraction(value) for value in candidate.coefficients]
    derivative = [
        coefficient * exponent
        for exponent, coefficient in enumerate(answer[1:], start=1)
    ]
    expected = _parse_coefficients(problem)
    width = max(len(derivative), len(expected))
    derivative.extend([Fraction(0)] * (width - len(derivative)))
    expected.extend([Fraction(0)] * (width - len(expected)))
    return derivative == expected


def _check_definite_integral(
    problem: dict[str, Any], candidate: PolynomialDefiniteIntegralAnswer
) -> bool:
    expected = _definite_integral_termwise(problem)
    try:
        actual = Fraction(candidate.value)
    except (ValueError, ZeroDivisionError):
        return False
    return actual == expected


def _candidate_symbols(
    problem: ExpressionDifferentiateProblem,
) -> dict[str, sympy.Symbol]:
    return build_symbols(
        [
            SymbolSpec(
                name=symbol.name,
                domain="real",
                positive=symbol.positive,
                nonzero=symbol.nonzero,
            )
            for symbol in problem.symbols
        ]
    )


def _candidate_equivalent(
    problem: ExpressionDifferentiateProblem, candidate: Expr
) -> bool:
    try:
        _walk(candidate)
        assumptions = {symbol.name: symbol for symbol in problem.symbols}
        unknown = _expr_symbols(candidate) - set(assumptions)
        if unknown:
            return False
        _validate_domain(candidate, assumptions)
        symbols = _candidate_symbols(problem)
        source = compile_expr(problem.expression, symbols)
        target = compile_expr(candidate, symbols)
    except (ValueError, MathCompileError):
        return False
    try:
        derived = sympy.diff(source, symbols[problem.variable])
    except (TypeError, ValueError):
        return False
    difference = derived - target
    try:
        if sympy.simplify(difference) == 0:
            return True
        if sympy.simplify(sympy.expand(difference)) == 0:
            return True
        if sympy.simplify(sympy.cancel(difference)) == 0:
            return True
        if sympy.simplify(sympy.trigsimp(difference)) == 0:
            return True
    except (TypeError, ValueError, ZeroDivisionError):
        return False
    return False


def check_answer(
    contract_id: str, problem: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    descriptor = _descriptor(contract_id)
    validated = validate_problem(contract_id, problem)
    parsed = _answer_model(contract_id, candidate)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        assert isinstance(parsed, PolynomialAntiderivativeAnswer)
        return _check_antiderivative(validated, parsed)
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        assert isinstance(parsed, PolynomialDefiniteIntegralAnswer)
        return _check_definite_integral(validated, parsed)
    if contract_id == DIFFERENTIATE_CONTRACT:
        assert isinstance(parsed, ExpressionDifferentiateAnswer)
        try:
            differentiate_problem = ExpressionDifferentiateProblem.model_validate(
                validated
            )
        except ValidationError:
            return False
        _ = descriptor
        return _candidate_equivalent(differentiate_problem, parsed.expression)
    raise ValueError(f"unknown calculus contract {contract_id!r}")


def _bounded_fraction(value: Fraction) -> Fraction:
    if (
        value.numerator.bit_length() > MAX_ARITHMETIC_BITS
        or value.denominator.bit_length() > MAX_ARITHMETIC_BITS
    ):
        raise ValueError("expression exceeds the exact arithmetic budget")
    return value


def _num(value: Fraction | int) -> Expr:
    return Expr(num=str(_bounded_fraction(Fraction(value))))


def _sym(name: str) -> Expr:
    return Expr(sym=name)


def _is_zero(expr: Expr) -> bool:
    return expr.num is not None and Fraction(expr.num) == 0


def _simplify(expr: Expr) -> Expr:
    if expr.op is None:
        return expr
    if expr.op == "add":
        terms: list[Expr] = []
        constant = Fraction(0)
        for child in (_simplify(arg) for arg in expr.args):
            if child.num is not None:
                constant = _bounded_fraction(constant + Fraction(child.num))
            elif child.op == "add":
                terms.extend(child.args)
            else:
                terms.append(child)
        if constant:
            terms.append(_num(constant))
        if not terms:
            return _num(0)
        if len(terms) == 1:
            return terms[0]
        return Expr(op="add", args=terms)
    if expr.op == "mul":
        factors: list[Expr] = []
        constant = Fraction(1)
        for child in (_simplify(arg) for arg in expr.args):
            if child.num is not None:
                constant = _bounded_fraction(constant * Fraction(child.num))
            elif child.op == "mul":
                factors.extend(child.args)
            else:
                factors.append(child)
        if constant == 0:
            return _num(0)
        if constant != 1 or not factors:
            factors.insert(0, _num(constant))
        if len(factors) == 1:
            return factors[0]
        return Expr(op="mul", args=factors)
    if expr.op == "sub":
        left = _simplify(expr.args[0])
        right = _simplify(expr.args[1])
        if left.num is not None and right.num is not None:
            return _num(Fraction(left.num) - Fraction(right.num))
        return _simplify(
            Expr(op="add", args=[left, Expr(op="mul", args=[_num(-1), right])])
        )
    if expr.op == "div":
        numerator = _simplify(expr.args[0])
        denominator = _simplify(expr.args[1])
        if _is_zero(numerator):
            return _num(0)
        if denominator.num is not None:
            value = Fraction(denominator.num)
            if value == 0:
                return expr
            if value == 1:
                return numerator
            if numerator.num is not None:
                return _num(Fraction(numerator.num) / value)
        return Expr(op="div", args=[numerator, denominator])
    if expr.op == "pow":
        base = _simplify(expr.args[0])
        exponent = _integer_exponent(expr.args[1])
        if exponent == 0:
            return _num(1)
        if exponent == 1:
            return base
        if base.num is not None:
            value = Fraction(base.num)
            if (
                value.numerator.bit_length() * abs(exponent) > MAX_ARITHMETIC_BITS
                or value.denominator.bit_length() * abs(exponent) > MAX_ARITHMETIC_BITS
            ):
                raise ValueError("expression exceeds the exact arithmetic budget")
            return _num(value**exponent)
        return Expr(op="pow", args=[base, _num(exponent)])
    return Expr(op=expr.op, args=[_simplify(arg) for arg in expr.args])


def _add(parts: list[Expr]) -> Expr:
    return _simplify(Expr(op="add", args=parts)) if parts else _num(0)


def _mul(parts: list[Expr]) -> Expr:
    return _simplify(Expr(op="mul", args=parts)) if parts else _num(1)


def _differentiate(expr: Expr, variable: str) -> Expr:
    if expr.num is not None:
        return _num(0)
    if expr.sym is not None:
        return _num(1 if expr.sym == variable else 0)
    op = expr.op
    assert op is not None
    if op == "add":
        return _add([_differentiate(arg, variable) for arg in expr.args])
    if op == "sub":
        return _simplify(
            Expr(
                op="sub",
                args=[
                    _differentiate(expr.args[0], variable),
                    _differentiate(expr.args[1], variable),
                ],
            )
        )
    if op == "mul":
        terms: list[Expr] = []
        for index, argument in enumerate(expr.args):
            derivative = _differentiate(argument, variable)
            if _is_zero(derivative):
                continue
            terms.append(
                _mul(
                    [
                        derivative,
                        *[
                            other
                            for position, other in enumerate(expr.args)
                            if position != index
                        ],
                    ]
                )
            )
        return _add(terms)
    if op == "div":
        numerator, denominator = expr.args
        derivative = Expr(
            op="div",
            args=[
                Expr(
                    op="sub",
                    args=[
                        _mul(
                            [
                                _differentiate(numerator, variable),
                                denominator,
                            ]
                        ),
                        _mul(
                            [
                                numerator,
                                _differentiate(denominator, variable),
                            ]
                        ),
                    ],
                ),
                Expr(op="pow", args=[denominator, _num(2)]),
            ],
        )
        return _simplify(derivative)
    if op == "pow":
        base, exponent_expr = expr.args
        exponent = _integer_exponent(exponent_expr)
        if exponent == 0:
            return _num(0)
        return _mul(
            [
                _num(exponent),
                Expr(op="pow", args=[base, _num(exponent - 1)]),
                _differentiate(base, variable),
            ]
        )
    if op == "sin":
        return _mul(
            [
                Expr(op="cos", args=[expr.args[0]]),
                _differentiate(expr.args[0], variable),
            ]
        )
    if op == "cos":
        return _mul(
            [
                _num(-1),
                Expr(op="sin", args=[expr.args[0]]),
                _differentiate(expr.args[0], variable),
            ]
        )
    if op == "exp":
        return _mul(
            [
                Expr(op="exp", args=[expr.args[0]]),
                _differentiate(expr.args[0], variable),
            ]
        )
    if op == "log":
        return _simplify(
            Expr(
                op="div",
                args=[
                    _differentiate(expr.args[0], variable),
                    expr.args[0],
                ],
            )
        )
    raise ValueError(f"unsupported operation {op!r}")


def _render_polynomial(coefficients: list[str], variable: str) -> str:
    values = [Fraction(value) for value in coefficients]
    parts: list[tuple[int, Fraction]] = [
        (exponent, coefficient)
        for exponent, coefficient in enumerate(values)
        if coefficient
    ]
    if not parts:
        return "0"
    pieces: list[str] = []
    for exponent, coefficient in reversed(parts):
        magnitude = abs(coefficient)
        if exponent == 0:
            body = str(magnitude)
        else:
            power = variable if exponent == 1 else f"{variable}^{exponent}"
            body = power if magnitude == 1 else f"{magnitude}{power}"
        if not pieces:
            pieces.append(("-" if coefficient < 0 else "") + body)
        else:
            pieces.append((" - " if coefficient < 0 else " + ") + body)
    return "".join(pieces)


def _render_expr(expr: Expr) -> str:
    if expr.num is not None:
        return expr.num
    if expr.sym is not None:
        return expr.sym
    op = expr.op
    assert op is not None
    if op == "add":
        return " + ".join(_render_expr(arg) for arg in expr.args)
    if op == "mul":
        return " * ".join(_render_expr(arg) for arg in expr.args)
    if op == "sub":
        return f"({_render_expr(expr.args[0])} - {_render_expr(expr.args[1])})"
    if op == "div":
        return f"({_render_expr(expr.args[0])})/({_render_expr(expr.args[1])})"
    if op == "pow":
        return f"({_render_expr(expr.args[0])})^({_render_expr(expr.args[1])})"
    return f"{op}({_render_expr(expr.args[0])})"


def render_problem(contract_id: str, problem: dict[str, Any]) -> str:
    validated = validate_problem(contract_id, problem)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        polynomial = _render_polynomial(validated["coefficients"], "x")
        request = (
            "Find the general antiderivative (include +C)."
            if validated["general"]
            else "Find one antiderivative."
        )
        return f"{request} d/dx F(x) = {polynomial}"
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        polynomial = _render_polynomial(validated["coefficients"], "x")
        return (
            f"Evaluate the definite integral of {polynomial} from "
            f"x={validated['lower']} to x={validated['upper']}."
        )
    parsed = ExpressionDifferentiateProblem.model_validate(validated)
    assumptions = []
    for symbol in parsed.symbols:
        facts = ["real"]
        if symbol.positive:
            facts = ["positive", "nonzero"]
        elif symbol.nonzero:
            facts = ["nonzero"]
        assumptions.append(f"{symbol.name}: " + ", ".join(facts))
    return (
        f"Differentiate {_render_expr(parsed.expression)} with respect to "
        f"{parsed.variable} (domain facts: {'; '.join(assumptions)})."
    )


def render_answer(contract_id: str, candidate: dict[str, Any]) -> str:
    parsed = _answer_model(contract_id, candidate)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        assert isinstance(parsed, PolynomialAntiderivativeAnswer)
        polynomial = _render_polynomial(parsed.coefficients, "x")
        return f"{polynomial} + C" if parsed.general else polynomial
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        assert isinstance(parsed, PolynomialDefiniteIntegralAnswer)
        return parsed.value
    assert isinstance(parsed, ExpressionDifferentiateAnswer)
    return _render_expr(parsed.expression)


def _antiderivative_wrong(problem: dict[str, Any]) -> list[dict[str, Any]]:
    expected = _antiderivative_answer(problem)
    base = [Fraction(value) for value in expected["coefficients"]]
    variants: list[dict[str, Any]] = [
        {
            "kind": expected["kind"],
            "coefficients": expected["coefficients"],
            "general": not expected["general"],
        }
    ]
    for delta in (1, -1, 2, -2, 3):
        changed = list(base)
        if len(changed) == 1:
            changed.append(Fraction(delta))
        else:
            changed[1] += delta
        variants.append(
            {
                "kind": expected["kind"],
                "coefficients": [str(value) for value in changed],
                "general": expected["general"],
            }
        )
    return _unique_wrong(ANTIDERIVATIVE_CONTRACT, problem, variants)


def _definite_wrong(problem: dict[str, Any]) -> list[dict[str, Any]]:
    expected = _definite_integral_answer(problem)
    value = Fraction(expected["value"])
    variants = [
        {
            "kind": expected["kind"],
            "value": str(value + delta),
        }
        for delta in (1, -1, 2, -2, 3)
    ]
    return _unique_wrong(DEFINITE_INTEGRAL_CONTRACT, problem, variants)


def _differentiate_wrong(problem: dict[str, Any]) -> list[dict[str, Any]]:
    expected = expected_answer(DIFFERENTIATE_CONTRACT, problem)
    base = Expr.model_validate(expected["expression"])
    variants: list[dict[str, Any]] = []
    for offset in (1, 2, 3, 4, 5):
        candidate = _simplify(Expr(op="add", args=[base, _num(offset)]))
        variants.append(
            {
                "kind": expected["kind"],
                "expression": _expr_dump(candidate),
            }
        )
    return _unique_wrong(DIFFERENTIATE_CONTRACT, problem, variants)


def _unique_wrong(
    contract_id: str, problem: dict[str, Any], variants: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Deduplicate independently-constructed wrong answers.

    Construction, not ``check_answer``, establishes wrongness. Filtering with
    the checker would let a checker false positive hide itself from
    qualification.
    """
    _ = (contract_id, problem)
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in variants:
        marker = repr(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        accepted.append(candidate)
    return accepted


def wrong_answers(
    contract_id: str, problem: dict[str, Any], answer: dict[str, Any]
) -> list[dict[str, Any]]:
    validated = validate_problem(contract_id, problem)
    # The supplied answer is checked for reachability in tests; the wrong list
    # is derived independently so it never trusts a model-provided answer.
    _answer_model(contract_id, answer)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        return _antiderivative_wrong(validated)
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        return _definite_wrong(validated)
    if contract_id == DIFFERENTIATE_CONTRACT:
        return _differentiate_wrong(validated)
    raise ValueError(f"unknown calculus contract {contract_id!r}")


def _fraction_strategy(
    *, minimum: int = -6, maximum: int = 6, max_denominator: int = 4
) -> st.SearchStrategy[str]:
    return st.fractions(
        min_value=minimum,
        max_value=maximum,
        max_denominator=max_denominator,
    ).map(str)


def _polynomial_strategy(
    *, maximum_length: int = MAX_DEGREE + 1
) -> st.SearchStrategy[list[str]]:
    return st.lists(
        _fraction_strategy(),
        min_size=1,
        max_size=maximum_length,
    )


def _safe_positive_expression() -> st.SearchStrategy[dict[str, Any]]:
    x = {"sym": "x"}
    safe = st.one_of(
        st.just(x),
        st.just({"op": "exp", "args": [x]}),
        st.just(
            {
                "op": "add",
                "args": [
                    {"op": "pow", "args": [x, {"num": "2"}]},
                    {"num": "1"},
                ],
            }
        ),
    )
    return safe


def _expression_strategy() -> st.SearchStrategy[dict[str, Any]]:
    x = {"sym": "x"}
    leaves = st.one_of(
        _fraction_strategy(minimum=-4, maximum=4).map(lambda value: {"num": value}),
        st.just(x),
        st.just({"op": "exp", "args": [x]}),
        st.just({"op": "sin", "args": [x]}),
        st.just({"op": "cos", "args": [x]}),
        st.just({"op": "log", "args": [x]}),
    )

    def extend(
        children: st.SearchStrategy[dict[str, Any]],
    ) -> st.SearchStrategy[dict[str, Any]]:
        return st.one_of(
            st.builds(
                lambda a, b: {"op": "add", "args": [a, b]},
                children,
                children,
            ),
            st.builds(
                lambda a, b: {"op": "sub", "args": [a, b]},
                children,
                children,
            ),
            st.builds(
                lambda a, b: {"op": "mul", "args": [a, b]},
                children,
                children,
            ),
            st.builds(
                lambda a, b: {"op": "div", "args": [a, b]},
                children,
                _safe_positive_expression(),
            ),
            st.builds(
                lambda a: {"op": "sin", "args": [a]},
                children,
            ),
            st.builds(
                lambda a: {"op": "cos", "args": [a]},
                children,
            ),
            st.builds(
                lambda a: {"op": "exp", "args": [a]},
                children,
            ),
            st.builds(
                lambda a: {"op": "log", "args": [a]},
                _safe_positive_expression(),
            ),
            st.builds(
                lambda a, n: {
                    "op": "pow",
                    "args": [a, {"num": str(n)}],
                },
                children,
                st.integers(min_value=1, max_value=4),
            ),
        )

    return st.recursive(leaves, extend, max_leaves=8)


def problem_strategy(contract_id: str) -> st.SearchStrategy[dict[str, Any]]:
    _descriptor(contract_id)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        return st.builds(
            lambda coefficients, general: {
                "kind": "polynomial_antiderivative",
                "coefficients": coefficients,
                "general": general,
            },
            _polynomial_strategy(),
            st.booleans(),
        )
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        return st.builds(
            lambda coefficients, lower, upper: {
                "kind": "polynomial_definite_integral",
                "coefficients": coefficients,
                "lower": lower,
                "upper": upper,
            },
            _polynomial_strategy(),
            _fraction_strategy(minimum=-4, maximum=4),
            _fraction_strategy(minimum=-4, maximum=4),
        )
    return st.builds(
        lambda expression: {
            "kind": "expression_differentiate",
            "expression": expression,
            "symbols": [{"name": "x", "positive": True, "nonzero": True}],
        },
        _expression_strategy(),
    )


def boundary_problems(contract_id: str) -> list[dict[str, Any]]:
    _descriptor(contract_id)
    if contract_id == ANTIDERIVATIVE_CONTRACT:
        return [
            {
                "kind": "polynomial_antiderivative",
                "coefficients": ["0"],
                "general": True,
            },
            {
                "kind": "polynomial_antiderivative",
                "coefficients": ["7"],
                "general": False,
            },
            {
                "kind": "polynomial_antiderivative",
                "coefficients": ["1/2", "0", "-3/4", "5"],
                "general": True,
            },
            {
                "kind": "polynomial_antiderivative",
                "coefficients": ["1", "2", "3", "4", "5", "6"],
                "general": False,
            },
        ]
    if contract_id == DEFINITE_INTEGRAL_CONTRACT:
        return [
            {
                "kind": "polynomial_definite_integral",
                "coefficients": ["1", "0", "3"],
                "lower": "2",
                "upper": "2",
            },
            {
                "kind": "polynomial_definite_integral",
                "coefficients": ["1", "0", "3"],
                "lower": "2",
                "upper": "-1",
            },
            {
                "kind": "polynomial_definite_integral",
                "coefficients": ["0"],
                "lower": "-5",
                "upper": "7",
            },
            {
                "kind": "polynomial_definite_integral",
                "coefficients": ["1/3", "-1/2", "2/5"],
                "lower": "-1/2",
                "upper": "3/2",
            },
        ]
    x = {"sym": "x"}
    return [
        {
            "kind": "expression_differentiate",
            "expression": x,
            "symbols": [{"name": "x", "positive": True, "nonzero": True}],
        },
        {
            "kind": "expression_differentiate",
            "expression": {
                "op": "add",
                "args": [
                    {
                        "op": "mul",
                        "args": [
                            {"num": "3"},
                            {"op": "pow", "args": [x, {"num": "2"}]},
                        ],
                    },
                    {"num": "-4"},
                ],
            },
            "symbols": [{"name": "x", "positive": True, "nonzero": True}],
        },
        {
            "kind": "expression_differentiate",
            "expression": {"op": "sin", "args": [x]},
            "symbols": [{"name": "x", "positive": True, "nonzero": True}],
        },
        {
            "kind": "expression_differentiate",
            "expression": {"op": "log", "args": [x]},
            "symbols": [{"name": "x", "positive": True, "nonzero": True}],
        },
        {
            "kind": "expression_differentiate",
            "expression": {"op": "div", "args": [{"num": "1"}, x]},
            "symbols": [{"name": "x", "positive": False, "nonzero": True}],
        },
        {
            "kind": "expression_differentiate",
            "expression": {
                "op": "mul",
                "args": [
                    {"op": "sin", "args": [x]},
                    {"op": "exp", "args": [x]},
                ],
            },
            "symbols": [{"name": "x", "positive": True, "nonzero": True}],
        },
    ]


__all__ = [
    "ANTIDERIVATIVE_CONTRACT",
    "CONTRACT_SPECS",
    "DEFINITE_INTEGRAL_CONTRACT",
    "DIFFERENTIATE_CONTRACT",
    "PROBLEM_TYPES",
    "boundary_problems",
    "check_answer",
    "expected_answer",
    "problem_strategy",
    "render_answer",
    "render_problem",
    "validate_problem",
    "wrong_answers",
]
