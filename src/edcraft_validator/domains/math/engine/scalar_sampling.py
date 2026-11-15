"""Exact rational point sampling for rejecting identities and guards."""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING

import sympy

from edcraft_validator.domains.math.engine.conditions import Condition
from edcraft_validator.domains.math.engine.context import EngineContext

if TYPE_CHECKING:
    from edcraft_validator.domains.math.engine.scalar_domains import Domain


def as_bool(value: object) -> bool | None:
    if value is True or value is sympy.true:
        return True
    if value is False or value is sympy.false:
        return False
    return None


def relational_truth(relation: sympy.Rel) -> bool | None:
    direct = as_bool(relation)
    if direct is not None:
        return direct
    try:
        simplified = sympy.simplify(relation)
    except (TypeError, ValueError):
        simplified = relation
    return as_bool(simplified)


_SUBS_VALUES = (
    sympy.S.Zero,
    sympy.S.One,
    sympy.S.NegativeOne,
    sympy.S(2),
    sympy.S(-2),
    sympy.Rational(1, 2),
    sympy.Rational(-1, 2),
    sympy.S(3),
    sympy.S(-3),
    sympy.Rational(1, 3),
    sympy.Rational(-1, 3),
    sympy.S(4),
    sympy.S(-4),
)


def sample_points(
    symbols: list[sympy.Symbol], ctx: EngineContext
) -> list[dict[sympy.Symbol, sympy.Expr]]:
    if not symbols:
        return [{}]
    values = _SUBS_VALUES if len(symbols) <= 3 else _SUBS_VALUES[:8]
    per_symbol = [
        [value for value in values if _sample_allowed(symbol, value, ctx)]
        for symbol in symbols
    ]

    if any(not choices for choices in per_symbol):
        return []

    # A fixed seed keeps the engine deterministic. Diagonals plus independent
    # draws cover all coordinates without walking a Cartesian prefix.
    rng = Random(0)
    combinations = [
        tuple(choices[index % len(choices)] for choices in per_symbol)
        for index in range(max(map(len, per_symbol)))
    ]
    combinations.extend(
        tuple(rng.choice(choices) for choices in per_symbol) for _ in range(96)
    )
    unique = dict.fromkeys(combinations)

    return [dict(zip(symbols, values, strict=True)) for values in unique]


def _sample_allowed(
    symbol: sympy.Symbol, value: sympy.Expr, ctx: EngineContext
) -> bool:
    spec = next(
        (item for item in ctx.request.problem.symbols if item.name == symbol.name),
        None,
    )
    if spec is None:
        return True
    if (spec.domain == "integer" or spec.integer) and value.q != 1:
        return False
    if spec.domain == "rational" and not value.is_rational:
        return False
    if spec.positive and value <= 0:
        return False
    if spec.nonzero and value == 0:
        return False
    return True


def find_satisfying_point(
    ctx: EngineContext, domain: Domain
) -> dict[sympy.Symbol, sympy.Expr] | None:
    symbols: set[sympy.Symbol] = set()
    if domain.variable is not None:
        symbols.add(domain.variable)
    for condition in domain.conditions:
        symbols.update(condition.expr.free_symbols)

    ordered = sorted(symbols, key=lambda item: item.name)
    for point in sample_points(ordered, ctx):
        if point_in_domain(point, domain):
            return point

    return None


def find_condition_violation(
    source_conditions: tuple[Condition, ...],
    target: Condition,
    ctx: EngineContext,
) -> dict[sympy.Symbol, sympy.Expr] | None:
    symbols = set(target.expr.free_symbols)
    for condition in source_conditions:
        symbols.update(condition.expr.free_symbols)

    ordered = sorted(symbols, key=lambda item: item.name)
    for point in sample_points(ordered, ctx):
        if not all(
            _condition_truth_at(condition, point) is True
            for condition in source_conditions
        ):
            continue
        if _condition_truth_at(target, point) is False:
            return point

    return None


def _condition_truth_at(
    condition: Condition,
    point: dict[sympy.Symbol, sympy.Expr],
) -> bool | None:
    try:
        substituted = sympy.sympify(condition.expr).subs(point)
    except (TypeError, ValueError):
        return None
    if substituted.has(sympy.nan, sympy.zoo, sympy.oo, -sympy.oo):
        return None
    try:
        relation = {
            "ne": lambda: sympy.Ne(substituted, 0),
            "gt": lambda: sympy.Gt(substituted, 0),
            "ge": lambda: sympy.Ge(substituted, 0),
            "lt": lambda: sympy.Lt(substituted, 0),
            "le": lambda: sympy.Le(substituted, 0),
        }[condition.kind]()
    except TypeError:
        # The condition is not real at this exact point (e.g. ``gt sqrt(a)`` at
        # ``a = -1``). That is not a violation of the condition; the point is
        # simply outside its real domain, so its truth stays unknown.
        return None

    return relational_truth(relation)


def point_in_domain(point: dict[sympy.Symbol, sympy.Expr], domain: Domain) -> bool:
    if domain.point_set is not None and domain.variable is not None:
        value = point.get(domain.variable)
        if value is None:
            return False
        try:
            contains = as_bool(domain.point_set.contains(value))
        except (TypeError, ValueError):
            contains = None
        if contains is not True:
            return False

    return all(
        _condition_truth_at(condition, point) is True for condition in domain.conditions
    )


def value_is_zero(expr: sympy.Expr, point: dict[sympy.Symbol, sympy.Expr]) -> bool:
    value = _evaluate_exact(expr, point)
    return value is not None and value == 0


def value_is_nonzero(expr: sympy.Expr, point: dict[sympy.Symbol, sympy.Expr]) -> bool:
    value = _evaluate_exact(expr, point)
    if value is None or value == 0 or value.is_real is not True:
        return False
    return value.is_zero is False


def _evaluate_exact(
    expr: sympy.Expr, point: dict[sympy.Symbol, sympy.Expr]
) -> sympy.Expr | None:
    try:
        value = sympy.sympify(expr).subs(point)
    except (TypeError, ValueError):
        return None
    if value.free_symbols:
        return None
    try:
        value = sympy.simplify(value)
    except (TypeError, ValueError):
        return None
    if value.has(sympy.nan, sympy.zoo, sympy.oo, -sympy.oo):
        return None
    return value


def simple_zero(expr: sympy.Expr) -> bool:
    if expr == 0 or expr.is_zero is True:
        return True
    transforms = (
        sympy.simplify,
        lambda value: sympy.cancel(sympy.together(value)),
        sympy.expand,
        sympy.trigsimp,
        sympy.factor,
        sympy.radsimp,
    )

    for transform in transforms:
        try:
            result = transform(expr)
        except (TypeError, ValueError):
            continue
        if result == 0 or result.is_zero is True:
            return True
    return False
