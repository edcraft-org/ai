"""Trusted univariate polynomial data, rendering, and a closed parser.

The pilot never evaluates a string. The parser below is a small recursive
descent for the declared polynomial grammar; every operation is degree- and
coefficient-bounded before the next step.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

MAX_DEGREE = 5
MAX_ABS_COEFFICIENT = 10_000
MAX_TEXT_LENGTH = 200
MAX_TOKENS = 120
VARIABLE = "x"


class PolynomialError(ValueError):
    """The value is outside the bounded univariate polynomial scope."""


def _checked(coefficients: tuple[int, ...]) -> tuple[int, ...]:
    if len(coefficients) - 1 > MAX_DEGREE:
        raise PolynomialError(f"polynomial degree exceeds {MAX_DEGREE}")
    for coefficient in coefficients:
        if type(coefficient) is not int:
            raise PolynomialError("polynomial coefficients must be integers")
        if abs(coefficient) > MAX_ABS_COEFFICIENT:
            raise PolynomialError("polynomial coefficient is out of bounds")
    return coefficients


@dataclass(frozen=True, slots=True)
class Polynomial:
    """Ascending coefficient tuple with trailing zeros removed."""

    coefficients: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        trimmed = list(self.coefficients)
        while trimmed and trimmed[-1] == 0:
            trimmed.pop()
        _checked(tuple(trimmed))
        object.__setattr__(self, "coefficients", tuple(trimmed))

    @classmethod
    def from_coefficients(cls, values: list[int] | tuple[int, ...]) -> Polynomial:
        return cls(tuple(values))

    @property
    def is_zero(self) -> bool:
        return not self.coefficients

    @property
    def degree(self) -> int:
        return len(self.coefficients) - 1

    def coefficient(self, exponent: int) -> int:
        if exponent < 0 or exponent >= len(self.coefficients):
            return 0
        return self.coefficients[exponent]

    def derivative(self) -> Polynomial:
        if self.is_zero:
            return Polynomial()
        return Polynomial(
            tuple(
                self.coefficients[index] * index
                for index in range(1, len(self.coefficients))
            )
        )

    def evaluate(self, point: int) -> int:
        value = 0
        for coefficient in reversed(self.coefficients):
            value = value * point + coefficient
        return value


def derivative_via_coefficients(problem: Polynomial) -> Polynomial:
    """Independent oracle: d/dx sum(a_i x^i) = sum(i a_i x^(i-1))."""
    result: list[int] = []
    for power in range(1, len(problem.coefficients)):
        result.append(problem.coefficients[power] * power)
    return Polynomial.from_coefficients(result)


def derivative_via_sympy(problem: Polynomial) -> Polynomial:
    """Trusted differentiate adapter: real SymPy over closed coefficient data.

    Only already-bounded ``Polynomial`` data crosses the boundary. The adapter
    builds a SymPy ``Poly`` from the coefficient map directly and never parses,
    evaluates, or formats a symbolic string.
    """
    if not isinstance(problem, Polynomial):
        raise PolynomialError("differentiation requires bounded polynomial data")
    import sympy

    variable = sympy.Symbol(VARIABLE)
    if problem.is_zero:
        source = sympy.Poly(0, variable)
    else:
        source = sympy.Poly.from_dict(
            {
                exponent: coefficient
                for exponent, coefficient in enumerate(problem.coefficients)
            },
            gens=variable,
        )
    differentiated = source.diff(variable)
    return Polynomial.from_coefficients(
        [int(coefficient) for coefficient in reversed(differentiated.all_coeffs())]
    )


def _term_text(coefficient: int, exponent: int, *, explicit: bool) -> str:
    magnitude = abs(coefficient)
    if exponent == 0:
        return str(magnitude)
    if magnitude == 1:
        body = f"{VARIABLE}^{exponent}" if exponent > 1 else VARIABLE
    else:
        body = f"{magnitude}{VARIABLE}"
        if exponent > 1:
            body += f"^{exponent}"
        if explicit:
            body = f"{magnitude}*{VARIABLE}"
            if exponent > 1:
                body += f"^{exponent}"
    return body


def render_polynomial(
    polynomial: Polynomial,
    *,
    explicit_multiplication: bool = False,
    ascending: bool = False,
) -> str:
    if polynomial.is_zero:
        return "0"
    exponents = list(range(len(polynomial.coefficients)))
    if not ascending:
        exponents.reverse()
    parts: list[str] = []
    for exponent in exponents:
        coefficient = polynomial.coefficient(exponent)
        if coefficient == 0:
            continue
        term = _term_text(coefficient, exponent, explicit=explicit_multiplication)
        if not parts:
            parts.append(("-" if coefficient < 0 else "") + term)
        else:
            parts.append((" - " if coefficient < 0 else " + ") + term)
    return "".join(parts)


def alternate_polynomial_forms(polynomial: Polynomial) -> list[str]:
    """All accepted renderings of one mathematical value, canonical first."""
    forms = [
        render_polynomial(polynomial),
        render_polynomial(polynomial, explicit_multiplication=True),
        render_polynomial(polynomial, ascending=True),
        f"({render_polynomial(polynomial)})",
    ]
    unique: list[str] = []
    for form in forms:
        if form not in unique:
            unique.append(form)
    return unique


def semantic_mutations(
    value: Polynomial, count: int, *, rng: random.Random | None = None
) -> list[Polynomial]:
    """Distinct, demonstrably wrong polynomials near ``value``."""
    if count <= 0:
        return []
    width = max(1, len(value.coefficients))
    candidates: list[Polynomial] = []

    def add(candidate: Polynomial) -> None:
        if candidate != value and candidate not in candidates:
            candidates.append(candidate)

    coefficients = list(value.coefficients) or [0]
    for index in range(width):
        for delta in (1, -1):
            changed = list(coefficients)
            changed[index] += delta
            try:
                add(Polynomial.from_coefficients(changed))
            except PolynomialError:
                pass
        current = coefficients[index]
        if current:
            changed = list(coefficients)
            changed[index] = -current
            try:
                add(Polynomial.from_coefficients(changed))
            except PolynomialError:
                pass
            if len(coefficients) > 1:
                changed = list(coefficients)
                changed[index] = 0
                try:
                    add(Polynomial.from_coefficients(changed))
                except PolynomialError:
                    pass
    for candidate in (
        Polynomial.from_coefficients([-coefficient for coefficient in coefficients]),
        Polynomial.from_coefficients([1, *coefficients]),
        Polynomial.from_coefficients([*coefficients, 1]),
        Polynomial.from_coefficients([*coefficients, -1]),
        Polynomial.from_coefficients([coefficients[0] + 1]),
    ):
        try:
            add(candidate)
        except PolynomialError:
            pass
    ordered = list(candidates)
    (rng or random.Random(0)).shuffle(ordered)
    return ordered[:count]


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.position = 0

    def _peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise PolynomialError("unexpected end of polynomial")
        self.position += 1
        return token

    def parse(self) -> Polynomial:
        value = self._expression()
        if self._peek() is not None:
            raise PolynomialError("unexpected token in polynomial")
        return value

    def _expression(self) -> Polynomial:
        value = self._term()
        while self._peek() in {"+", "-"}:
            operator = self._take()
            right = self._term()
            value = self._add(value, right, subtract=operator == "-")
        return value

    def _term(self) -> Polynomial:
        value = self._unary()
        while True:
            token = self._peek()
            if token == "*":
                self._take()
                value = self._multiply(value, self._unary())
            elif token is not None and (
                token == "(" or token == VARIABLE or token.isdigit()
            ):
                value = self._multiply(value, self._unary())
            else:
                return value

    def _unary(self) -> Polynomial:
        token = self._peek()
        if token == "-":
            self._take()
            return self._scale(self._unary(), -1)
        if token == "+":
            self._take()
            return self._unary()
        return self._power()

    def _power(self) -> Polynomial:
        value = self._primary()
        if self._peek() == "^":
            self._take()
            exponent_token = self._take()
            if not exponent_token.isdigit():
                raise PolynomialError("exponents must be integer literals")
            exponent = int(exponent_token)
            if exponent > MAX_DEGREE:
                raise PolynomialError("exponents are bounded")
            value = self._pow(value, exponent)
        return value

    def _primary(self) -> Polynomial:
        token = self._take()
        if token.isdigit():
            return Polynomial.from_coefficients([int(token)])
        if token == VARIABLE:
            return Polynomial.from_coefficients([0, 1])
        if token == "(":
            value = self._expression()
            if self._take() != ")":
                raise PolynomialError("unbalanced parentheses")
            return value
        raise PolynomialError(f"unsupported token {token!r}")

    @staticmethod
    def _add(left: Polynomial, right: Polynomial, *, subtract: bool) -> Polynomial:
        width = max(len(left.coefficients), len(right.coefficients))
        values = [0] * width
        for index in range(width):
            values[index] = left.coefficient(index) + (
                -right.coefficient(index) if subtract else right.coefficient(index)
            )
        try:
            return Polynomial.from_coefficients(values)
        except PolynomialError as exc:
            raise PolynomialError("polynomial addition is out of bounds") from exc

    @staticmethod
    def _multiply(left: Polynomial, right: Polynomial) -> Polynomial:
        if not left.coefficients or not right.coefficients:
            return Polynomial()
        values = [0] * (len(left.coefficients) + len(right.coefficients) - 1)
        for left_index, left_value in enumerate(left.coefficients):
            for right_index, right_value in enumerate(right.coefficients):
                values[left_index + right_index] += left_value * right_value
        try:
            return Polynomial.from_coefficients(values)
        except PolynomialError as exc:
            raise PolynomialError("polynomial product is out of bounds") from exc

    @classmethod
    def _scale(cls, value: Polynomial, factor: int) -> Polynomial:
        try:
            return Polynomial.from_coefficients(
                [factor * coefficient for coefficient in value.coefficients]
            )
        except PolynomialError as exc:
            raise PolynomialError("polynomial coefficient is out of bounds") from exc

    @classmethod
    def _pow(cls, value: Polynomial, exponent: int) -> Polynomial:
        result = Polynomial.from_coefficients([1])
        for _ in range(exponent):
            result = cls._multiply(result, value)
        return result


_TOKEN = re.compile(r"\d+|[xX]|[+\-*^()]")


def _tokenize(text: str) -> list[str]:
    if not isinstance(text, str):
        raise PolynomialError("polynomial text must be a string")
    if not text.strip():
        raise PolynomialError("polynomial text is empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise PolynomialError("polynomial text is too long")
    tokens: list[str] = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        match = _TOKEN.match(text, position)
        if match is None:
            raise PolynomialError(f"unsupported character {text[position]!r}")
        token = match.group(0)
        tokens.append(token if token not in {"x", "X"} else VARIABLE)
        position = match.end()
    if len(tokens) > MAX_TOKENS:
        raise PolynomialError("polynomial has too many tokens")
    return tokens


def parse_polynomial(text: str) -> Polynomial:
    """Parse the closed polynomial grammar; never evaluates code."""
    return _Parser(_tokenize(text)).parse()


__all__ = [
    "MAX_ABS_COEFFICIENT",
    "MAX_DEGREE",
    "Polynomial",
    "PolynomialError",
    "VARIABLE",
    "alternate_polynomial_forms",
    "derivative_via_coefficients",
    "derivative_via_sympy",
    "parse_polynomial",
    "render_polynomial",
    "semantic_mutations",
]
