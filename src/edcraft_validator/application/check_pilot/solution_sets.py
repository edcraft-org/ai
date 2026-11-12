"""Bounded real polynomial relations and complete real solution sets.

The independent qualification oracle below uses coefficient, discriminant and
sign arithmetic. The recipe-owned ``relation.solve_real`` operation uses a
separate SymPy path, so qualification does not confirm one function against
itself. Only closed, bounded data crosses either boundary; no string is ever
evaluated as Python.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from fractions import Fraction

import sympy

from edcraft_validator.application.check_pilot.models import (
    MAX_ENDPOINT_LENGTH,
    MAX_RELATION_COEFFICIENT,
    MAX_SET_COMPONENTS,
    MAX_SOLVE_DEGREE,
    PolynomialRelation,
    RealSetComponent,
    RealSolutionSet,
    RelationKind,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    PolynomialError,
    render_polynomial,
)

MAX_ENDPOINT_NODES = 80
MAX_ENDPOINT_DEPTH = 12
MAX_LITERAL = 1_000_000

_RELATION_TEXT = {"eq": "=", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}
_INVERSE_RELATION: dict[RelationKind, RelationKind] = {
    "lt": "gt",
    "le": "ge",
    "gt": "lt",
    "ge": "le",
    "eq": "eq",
}
_SYMPY_RELATIONS = {
    "lt": sympy.Lt,
    "le": sympy.Le,
    "gt": sympy.Gt,
    "ge": sympy.Ge,
}


class SolutionSetError(ValueError):
    """The relation or candidate set is outside the bounded closed grammar."""


@dataclass(frozen=True, slots=True)
class IntervalComponent:
    lower: sympy.Expr | None
    upper: sympy.Expr | None
    lower_closed: bool = True
    upper_closed: bool = True


@dataclass(frozen=True, slots=True)
class SolutionSet:
    components: tuple[IntervalComponent, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.components

    @property
    def is_all_real(self) -> bool:
        return (
            len(self.components) == 1
            and self.components[0].lower is None
            and self.components[0].upper is None
        )


def _all_real() -> SolutionSet:
    return SolutionSet((IntervalComponent(None, None, False, False),))


def _point(value: sympy.Expr) -> SolutionSet:
    return SolutionSet((IntervalComponent(value, value, True, True),))


def _interval(
    lower: sympy.Expr | None,
    upper: sympy.Expr | None,
    *,
    lower_closed: bool,
    upper_closed: bool,
) -> SolutionSet:
    return SolutionSet((IntervalComponent(lower, upper, lower_closed, upper_closed),))


def relation_data(relation: PolynomialRelation) -> tuple[RelationKind, tuple[int, ...]]:
    coefficients = tuple(relation.coefficients)
    if len(coefficients) > MAX_SOLVE_DEGREE + 1:
        raise SolutionSetError("relations are bounded to degree two")
    if any(abs(value) > MAX_RELATION_COEFFICIENT for value in coefficients):
        raise SolutionSetError("relation coefficients are out of bounds")
    return relation.relation, coefficients


def render_relation(relation: RelationKind, coefficients: tuple[int, ...]) -> str:
    polynomial = render_polynomial(Polynomial.from_coefficients(coefficients))
    return f"{polynomial} {_RELATION_TEXT[relation]} 0"


def question_text(relation: RelationKind, coefficients: tuple[int, ...]) -> str:
    return f"Solve for real x: {render_relation(relation, coefficients)}."


def _sign(value: sympy.Expr) -> int:
    simplified = sympy.simplify(value)
    if simplified == 0:
        return 0
    if simplified.is_positive is True:
        return 1
    if simplified.is_negative is True:
        return -1
    numeric = sympy.N(simplified, 80)
    if numeric.is_real is not True:
        raise SolutionSetError("solution endpoints must be real")
    real = float(numeric)
    if real > 0:
        return 1
    if real < 0:
        return -1
    return 0


def compare_endpoints(left: sympy.Expr | None, right: sympy.Expr | None) -> int:
    if left is None and right is None:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    return _sign(left - right)


def _merge(a: IntervalComponent, b: IntervalComponent) -> IntervalComponent:
    if a.lower is None or b.lower is None:
        lower: sympy.Expr | None = None
        lower_closed = False
    else:
        comparison = compare_endpoints(a.lower, b.lower)
        if comparison < 0:
            lower, lower_closed = a.lower, a.lower_closed
        elif comparison > 0:
            lower, lower_closed = b.lower, b.lower_closed
        else:
            lower = a.lower
            lower_closed = a.lower_closed or b.lower_closed
    if a.upper is None or b.upper is None:
        upper: sympy.Expr | None = None
        upper_closed = False
    else:
        comparison = compare_endpoints(a.upper, b.upper)
        if comparison > 0:
            upper, upper_closed = a.upper, a.upper_closed
        elif comparison < 0:
            upper, upper_closed = b.upper, b.upper_closed
        else:
            upper = a.upper
            upper_closed = a.upper_closed or b.upper_closed
    return IntervalComponent(lower, upper, lower_closed, upper_closed)


def normalize_components(
    components: tuple[IntervalComponent, ...],
) -> tuple[IntervalComponent, ...]:
    if any(item.lower is None and item.upper is None for item in components):
        return _all_real().components
    live: list[IntervalComponent] = []
    for item in components:
        if item.lower is not None and item.upper is not None:
            comparison = compare_endpoints(item.lower, item.upper)
            if comparison > 0:
                continue
            if comparison == 0 and not (item.lower_closed and item.upper_closed):
                continue
        live.append(item)
    live.sort(
        key=lambda item: (
            item.lower is not None,
            sympy.N(item.lower, 60) if item.lower is not None else 0,
            item.upper is not None,
            sympy.N(item.upper, 60) if item.upper is not None else 0,
        )
    )
    merged: list[IntervalComponent] = []
    for item in live:
        if not merged:
            merged.append(item)
            continue
        current = merged[-1]
        if current.upper is None or item.lower is None:
            merged[-1] = _merge(current, item)
            continue
        comparison = compare_endpoints(current.upper, item.lower)
        if comparison > 0 or (
            comparison == 0 and (current.upper_closed or item.lower_closed)
        ):
            merged[-1] = _merge(current, item)
        else:
            merged.append(item)
    return tuple(merged)


def normalize(solution: SolutionSet) -> SolutionSet:
    return SolutionSet(normalize_components(solution.components))


def sets_equal(left: SolutionSet, right: SolutionSet) -> bool:
    first = normalize(left).components
    second = normalize(right).components
    if len(first) != len(second):
        return False
    for a, b in zip(first, second, strict=True):
        if compare_endpoints(a.lower, b.lower) != 0:
            return False
        if compare_endpoints(a.upper, b.upper) != 0:
            return False
        if a.lower_closed != b.lower_closed or a.upper_closed != b.upper_closed:
            return False
    return True


def render_endpoint(value: sympy.Expr) -> str:
    text = sympy.sstr(sympy.simplify(value))
    if len(text) > MAX_ENDPOINT_LENGTH:
        raise SolutionSetError("solution endpoint is too long")
    return text


def render_component(component: IntervalComponent) -> str:
    if component.lower is None and component.upper is None:
        return "All real numbers"
    if (
        component.lower is not None
        and component.upper is not None
        and compare_endpoints(component.lower, component.upper) == 0
        and component.lower_closed
        and component.upper_closed
    ):
        return "{" + render_endpoint(component.lower) + "}"
    left = "[" if component.lower_closed and component.lower is not None else "("
    right = "]" if component.upper_closed and component.upper is not None else ")"
    lower = "-∞" if component.lower is None else render_endpoint(component.lower)
    upper = "∞" if component.upper is None else render_endpoint(component.upper)
    return f"{left}{lower}, {upper}{right}"


def render_solution_set(solution: SolutionSet) -> str:
    normalized = normalize(solution)
    if not normalized.components:
        return "No real solutions"
    return " ∪ ".join(render_component(item) for item in normalized.components)


def solution_set_model(solution: SolutionSet) -> RealSolutionSet:
    normalized = normalize(solution)
    components: list[RealSetComponent] = []
    for item in normalized.components:
        lower = None if item.lower is None else render_endpoint(item.lower)
        upper = None if item.upper is None else render_endpoint(item.upper)
        components.append(
            RealSetComponent(
                lower=lower,
                upper=upper,
                lower_closed=item.lower_closed if lower is not None else False,
                upper_closed=item.upper_closed if upper is not None else False,
            )
        )
    return RealSolutionSet(components=components)


_TOKEN = re.compile(r"\d+|[A-Za-z]+|[+\-*/().]")


class _EndpointParser:
    def __init__(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise SolutionSetError("endpoint text must be non-blank")
        if len(text) > MAX_ENDPOINT_LENGTH:
            raise SolutionSetError("endpoint text is too long")
        self.tokens: list[str] = []
        position = 0
        while position < len(text):
            if text[position].isspace():
                position += 1
                continue
            match = _TOKEN.match(text, position)
            if match is None:
                raise SolutionSetError(
                    f"unsupported endpoint character {text[position]!r}"
                )
            token = match.group(0)
            if token in {"**", "e", "E"}:
                raise SolutionSetError("unsupported endpoint syntax")
            self.tokens.append(token)
            position = match.end()
        if len(self.tokens) > MAX_ENDPOINT_NODES:
            raise SolutionSetError("endpoint expression is too large")
        self.position = 0

    def parse(self, depth: int = 0) -> sympy.Expr:
        if depth > MAX_ENDPOINT_DEPTH:
            raise SolutionSetError("endpoint expression is too deeply nested")
        value = self._term(depth + 1)
        while self._peek() in {"+", "-"}:
            operator = self._take()
            right = self._term(depth + 1)
            value = value + right if operator == "+" else value - right
        return value

    def _term(self, depth: int) -> sympy.Expr:
        value = self._unary(depth)
        while self._peek() in {"*", "/"}:
            operator = self._take()
            right = self._unary(depth)
            if operator == "*":
                value = value * right
            else:
                if right == 0:
                    raise SolutionSetError("endpoint expression divides by zero")
                value = value / right
        return value

    def _unary(self, depth: int) -> sympy.Expr:
        token = self._peek()
        if token == "+":
            self._take()
            return self._unary(depth)
        if token == "-":
            self._take()
            return -self._unary(depth)
        return self._primary(depth)

    def _primary(self, depth: int) -> sympy.Expr:
        token = self._take()
        if token.isdigit():
            value = int(token)
            if value > MAX_LITERAL:
                raise SolutionSetError("endpoint integer literal is too large")
            return sympy.Integer(value)
        if token == "sqrt":
            if self._take() != "(":
                raise SolutionSetError("sqrt requires parentheses")
            argument = self.parse(depth + 1)
            if self._take() != ")":
                raise SolutionSetError("unbalanced sqrt parentheses")
            if argument.is_nonnegative is not True:
                raise SolutionSetError("sqrt argument must be non-negative")
            return sympy.sqrt(argument)
        if token == "(":
            value = self.parse(depth + 1)
            if self._take() != ")":
                raise SolutionSetError("unbalanced parentheses")
            return value
        raise SolutionSetError(f"unsupported endpoint token {token!r}")

    def _peek(self) -> str | None:
        if self.position >= len(self.tokens):
            return None
        return self.tokens[self.position]

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise SolutionSetError("unexpected end of endpoint expression")
        self.position += 1
        return token


def parse_endpoint(text: str) -> sympy.Expr:
    """Parse the closed endpoint grammar without eval or parse_expr."""
    parser = _EndpointParser(text)
    value = parser.parse()
    if parser._peek() is not None:
        raise SolutionSetError("unexpected endpoint token")
    if value.is_real is not True:
        raise SolutionSetError("solution endpoints must be real")
    return value


def solution_set_from_model(model: RealSolutionSet) -> SolutionSet:
    if len(model.components) > MAX_SET_COMPONENTS:
        raise SolutionSetError("solution set has too many components")
    components: list[IntervalComponent] = []
    for item in model.components:
        lower = None if item.lower is None else parse_endpoint(item.lower)
        upper = None if item.upper is None else parse_endpoint(item.upper)
        components.append(
            IntervalComponent(
                lower,
                upper,
                item.lower_closed if lower is not None else False,
                item.upper_closed if upper is not None else False,
            )
        )
    if not components:
        return SolutionSet(())
    return normalize(SolutionSet(tuple(components)))


# ---------------------------------------------------------------------------
# Independent oracle: coefficient / discriminant / sign arithmetic.


def _quadratic_roots(a: int, b: int, c: int) -> tuple[sympy.Expr, sympy.Expr, int]:
    discriminant = b * b - 4 * a * c
    root = sympy.sqrt(discriminant)
    first = sympy.simplify((-b - root) / (2 * a))
    second = sympy.simplify((-b + root) / (2 * a))
    if compare_endpoints(first, second) > 0:
        first, second = second, first
    return first, second, discriminant


def _positive_intervals(
    first: sympy.Expr,
    second: sympy.Expr,
    *,
    inside: bool,
    closed: bool,
) -> SolutionSet:
    if inside:
        return _interval(first, second, lower_closed=closed, upper_closed=closed)
    return SolutionSet(
        (
            IntervalComponent(None, first, False, closed),
            IntervalComponent(second, None, closed, False),
        )
    )


def solve_relation_independently(
    relation: RelationKind, coefficients: tuple[int, ...]
) -> SolutionSet:
    """Construct the complete real set from coefficients, never from a solver."""
    if not coefficients:
        raise SolutionSetError("a relation requires at least one coefficient")
    if len(coefficients) > MAX_SOLVE_DEGREE + 1:
        raise SolutionSetError("relations are bounded to degree two")
    if any(abs(value) > MAX_RELATION_COEFFICIENT for value in coefficients):
        raise SolutionSetError("relation coefficients are out of bounds")
    values = list(coefficients)
    while len(values) > 1 and values[-1] == 0:
        values.pop()
    degree = len(values) - 1
    a = values[2] if degree >= 2 else 0
    b = values[1] if degree >= 1 else 0
    c = values[0]
    if degree <= 0:
        truth = {
            "eq": c == 0,
            "lt": c < 0,
            "le": c <= 0,
            "gt": c > 0,
            "ge": c >= 0,
        }[relation]
        return _all_real() if truth else SolutionSet(())
    if degree == 1:
        root = sympy.Rational(-c, b)
        positive_on_right = b > 0
        if relation == "eq":
            return _point(root)
        positive = (
            {
                "gt": _interval(root, None, lower_closed=False, upper_closed=False),
                "ge": _interval(root, None, lower_closed=True, upper_closed=False),
            }
            if positive_on_right
            else {
                "gt": _interval(None, root, lower_closed=False, upper_closed=False),
                "ge": _interval(None, root, lower_closed=False, upper_closed=True),
            }
        )
        negative = (
            {
                "lt": _interval(None, root, lower_closed=False, upper_closed=False),
                "le": _interval(None, root, lower_closed=False, upper_closed=True),
            }
            if positive_on_right
            else {
                "lt": _interval(root, None, lower_closed=False, upper_closed=False),
                "le": _interval(root, None, lower_closed=True, upper_closed=False),
            }
        )
        return positive.get(relation) or negative[relation]

    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        positive_everywhere = a > 0
        if relation == "eq":
            return SolutionSet(())
        if relation in {"gt", "ge"}:
            return _all_real() if positive_everywhere else SolutionSet(())
        return SolutionSet(()) if positive_everywhere else _all_real()
    first, second, _ = _quadratic_roots(a, b, c)
    if discriminant == 0:
        root = first
        if relation == "eq":
            return _point(root)
        if a > 0:
            if relation == "gt":
                return SolutionSet(
                    (
                        IntervalComponent(None, root, False, False),
                        IntervalComponent(root, None, False, False),
                    )
                )
            if relation == "ge":
                return _all_real()
            if relation == "le":
                return _point(root)
            return SolutionSet(())
        if relation == "lt":
            return SolutionSet(
                (
                    IntervalComponent(None, root, False, False),
                    IntervalComponent(root, None, False, False),
                )
            )
        if relation == "le":
            return _all_real()
        if relation == "ge":
            return _point(root)
        return SolutionSet(())
    if relation == "eq":
        return SolutionSet((_point(first).components[0], _point(second).components[0]))
    positive_inside = a < 0
    if relation in {"gt", "ge"}:
        return _positive_intervals(
            first,
            second,
            inside=positive_inside,
            closed=relation == "ge",
        )
    return _positive_intervals(
        first,
        second,
        inside=not positive_inside,
        closed=relation == "le",
    )


# ---------------------------------------------------------------------------
# Recipe-owned solver: a separate SymPy path.

_RELATIONAL_CONVERSION = {
    "eq": lambda expr: sympy.Eq(expr, 0),
    "lt": lambda expr: sympy.Lt(expr, 0),
    "le": lambda expr: sympy.Le(expr, 0),
    "gt": lambda expr: sympy.Gt(expr, 0),
    "ge": lambda expr: sympy.Ge(expr, 0),
}


def _sympy_endpoint(value: object) -> sympy.Expr | None:
    if value is sympy.S.NegativeInfinity or value is sympy.S.Infinity:
        return None
    if not isinstance(value, sympy.Expr):
        raise SolutionSetError("unsupported solution endpoint")
    return sympy.simplify(value)


def _components_from_sympy(value: object) -> tuple[IntervalComponent, ...]:
    if value is sympy.S.EmptySet:
        return ()
    if value is sympy.S.Reals:
        return _all_real().components
    if isinstance(value, sympy.FiniteSet):
        return tuple(IntervalComponent(item, item, True, True) for item in value.args)
    if isinstance(value, sympy.Interval):
        return (
            IntervalComponent(
                _sympy_endpoint(value.start),
                _sympy_endpoint(value.end),
                not value.left_open,
                not value.right_open,
            ),
        )
    if isinstance(value, sympy.Union):
        components: list[IntervalComponent] = []
        for argument in value.args:
            components.extend(_components_from_sympy(argument))
        return tuple(components)
    if isinstance(value, sympy.Complement):
        base, removed = value.args
        if base is sympy.S.Reals and isinstance(removed, sympy.FiniteSet):
            points = sorted(
                (sympy.simplify(item) for item in removed.args),
                key=lambda item: sympy.N(item, 60),
            )
            if not points:
                return _all_real().components
            pieces: list[IntervalComponent] = []
            lower: sympy.Expr | None = None
            lower_closed = False
            for point in points:
                pieces.append(IntervalComponent(lower, point, lower_closed, False))
                lower, lower_closed = point, False
            pieces.append(IntervalComponent(lower, None, lower_closed, False))
            return tuple(pieces)
    raise SolutionSetError("the trusted solver returned an unsupported set shape")


def solve_relation_via_sympy(
    relation: RelationKind, coefficients: tuple[int, ...]
) -> SolutionSet:
    """Recipe operation implementation; intentionally separate from the oracle."""
    if not coefficients:
        raise SolutionSetError("a relation requires at least one coefficient")
    if len(coefficients) > MAX_SOLVE_DEGREE + 1:
        raise SolutionSetError("relations are bounded to degree two")
    if any(abs(value) > MAX_RELATION_COEFFICIENT for value in coefficients):
        raise SolutionSetError("relation coefficients are out of bounds")
    variable = sympy.Symbol("x", real=True)
    expression = sum(
        sympy.Integer(coefficient) * variable**exponent
        for exponent, coefficient in enumerate(coefficients)
    )
    if relation == "eq":
        result = sympy.solveset(sympy.Eq(expression, 0), variable, domain=sympy.S.Reals)
    else:
        from sympy.solvers.inequalities import solve_univariate_inequality

        result = solve_univariate_inequality(
            _RELATIONAL_CONVERSION[relation](expression),
            variable,
            relational=False,
        )
    return normalize(SolutionSet(_components_from_sympy(result)))


# ---------------------------------------------------------------------------
# Wrong-answer mutations and public helpers.


def _component_endpoints(solution: SolutionSet) -> list[sympy.Expr]:
    values: list[sympy.Expr] = []
    for component in solution.components:
        if component.lower is not None:
            values.append(component.lower)
        if component.upper is not None:
            values.append(component.upper)
    return values


def solution_set_mutations(
    relation: RelationKind,
    coefficients: tuple[int, ...],
    expected: SolutionSet,
    count: int,
    *,
    rng: random.Random | None = None,
) -> list[SolutionSet]:
    """Non-vacuous wrong sets: missing roots, extras, flags and flipped relations."""
    if count <= 0:
        return []
    candidates: list[SolutionSet] = []
    rendered: set[str] = set()

    def add(candidate: SolutionSet) -> None:
        normalized = normalize(candidate)
        if sets_equal(normalized, expected):
            return
        try:
            text = render_solution_set(normalized)
        except (SolutionSetError, PolynomialError):
            return
        if text in rendered:
            return
        rendered.add(text)
        candidates.append(normalized)

    components = list(expected.components)
    for index in range(len(components)):
        add(SolutionSet(tuple(components[:index] + components[index + 1 :])))
    add(SolutionSet(()))
    add(_all_real())
    endpoints = _component_endpoints(expected)
    probes = [sympy.Integer(0), sympy.Integer(1), sympy.Integer(-1)]
    for endpoint in endpoints[:2]:
        probes.append(sympy.simplify(endpoint + 1))
        probes.append(sympy.simplify(endpoint - 1))
    for probe in probes:
        add(_point(probe))
    for index, component in enumerate(components):
        if component.lower is not None:
            flipped = IntervalComponent(
                component.lower,
                component.upper,
                not component.lower_closed,
                component.upper_closed,
            )
            add(
                SolutionSet(
                    tuple(components[:index] + [flipped] + components[index + 1 :])
                )
            )
        if component.upper is not None:
            flipped = IntervalComponent(
                component.lower,
                component.upper,
                component.lower_closed,
                not component.upper_closed,
            )
            add(
                SolutionSet(
                    tuple(components[:index] + [flipped] + components[index + 1 :])
                )
            )
        if component.upper is not None:
            shifted = IntervalComponent(
                component.lower,
                sympy.simplify(component.upper + 1),
                component.lower_closed,
                component.upper_closed,
            )
            add(
                SolutionSet(
                    tuple(components[:index] + [shifted] + components[index + 1 :])
                )
            )
    if relation != "eq":
        add(solve_relation_independently(_INVERSE_RELATION[relation], coefficients))
    ordered = list(candidates)
    (rng or random.Random(0)).shuffle(ordered)
    return ordered[:count]


def fraction_text(value: Fraction) -> str:
    """Render a rational value without floating point."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


__all__ = [
    "IntervalComponent",
    "SolutionSet",
    "SolutionSetError",
    "compare_endpoints",
    "fraction_text",
    "normalize",
    "parse_endpoint",
    "question_text",
    "relation_data",
    "render_endpoint",
    "render_relation",
    "render_solution_set",
    "sets_equal",
    "solution_set_from_model",
    "solution_set_model",
    "solution_set_mutations",
    "solve_relation_independently",
    "solve_relation_via_sympy",
]
