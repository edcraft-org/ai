"""Exact sign inference for expressions under the source domain's guards."""

from __future__ import annotations

from itertools import combinations

import sympy

from edcraft_validator.domains.math.engine.conditions import Condition
from edcraft_validator.domains.math.engine.scalar_sampling import simple_zero


def same_expr(left: sympy.Expr, right: sympy.Expr) -> bool:
    if left == right:
        return True
    try:
        return sympy.simplify(left - right) == 0
    except (TypeError, ValueError):
        return False


def sign_category(
    conditions: tuple[Condition, ...], expr: sympy.Expr
) -> frozenset[int] | None:
    """Return every sign an expression can take on the source domain.

    ``expr_sign`` commits to one sign; this helper carries non-strict facts
    such as "nonnegative". Products and powers of guarded quantities can then
    be classified exactly without sampling.
    """
    if expr.is_zero is True:
        return frozenset({0})
    if expr.is_positive is True:
        return frozenset({1})
    if expr.is_negative is True:
        return frozenset({-1})
    if expr.is_nonnegative is True:
        return frozenset({0, 1})
    if expr.is_nonpositive is True:
        return frozenset({-1, 0})
    if expr.is_nonzero is True:
        return frozenset({-1, 1})
    for condition in conditions:
        if not same_expr(condition.expr, expr):
            continue
        if condition.kind == "gt":
            return frozenset({1})
        if condition.kind == "ge":
            return frozenset({0, 1})
        if condition.kind == "lt":
            return frozenset({-1})
        if condition.kind == "le":
            return frozenset({-1, 0})
        if condition.kind == "ne":
            return frozenset({-1, 1})
    if isinstance(expr, sympy.Mul):
        categories = [sign_category(conditions, argument) for argument in expr.args]
        if any(category is None for category in categories):
            return None
        result = frozenset({1})
        for category in categories:
            assert category is not None
            result = frozenset(left * right for left in result for right in category)
        return result
    if isinstance(expr, sympy.Add):
        categories = [sign_category(conditions, argument) for argument in expr.args]
        if any(category is None for category in categories):
            return None
        if all(category == frozenset({1}) for category in categories):
            return frozenset({1})
        if all(category == frozenset({-1}) for category in categories):
            return frozenset({-1})
        if all(category <= frozenset({0, 1}) for category in categories):
            return frozenset({0, 1})
        if all(category <= frozenset({-1, 0}) for category in categories):
            return frozenset({-1, 0})
        return None
    if isinstance(expr, sympy.Pow):
        base, exponent = expr.args
        base_category = sign_category(conditions, base)
        if base_category is None:
            return None
        if exponent.is_zero is True:
            return frozenset({1})
        if exponent.is_Integer:
            if exponent % 2 == 0:
                if base_category == frozenset({0}):
                    return frozenset({0})
                if 0 not in base_category:
                    return frozenset({1})
                return frozenset({0, 1})
            return base_category
        if exponent.is_Rational and exponent.q % 2 != 0 and exponent > 0:
            if base_category == frozenset({1}):
                return frozenset({1})
            if base_category <= frozenset({0, 1}):
                return frozenset({0, 1})
        return None
    if isinstance(expr, sympy.Abs):
        argument_category = sign_category(conditions, expr.args[0])
        if argument_category is None:
            return None
        if argument_category == frozenset({0}):
            return frozenset({0})
        if 0 not in argument_category:
            return frozenset({1})
        return frozenset({0, 1})
    if isinstance(expr, sympy.exp):
        return frozenset({1})
    if isinstance(expr, sympy.sign):
        return frozenset({-1, 0, 1})
    return None


def expr_sign(conditions: tuple[Condition, ...], expr: sympy.Expr) -> int | None:
    if expr.is_zero is True:
        return 0
    if expr.is_positive is True:
        return 1
    if expr.is_negative is True:
        return -1
    for condition in conditions:
        if not same_expr(condition.expr, expr):
            continue
        if condition.kind == "gt":
            return 1
        if condition.kind == "lt":
            return -1
    if isinstance(expr, sympy.Mul):
        signs = [expr_sign(conditions, argument) for argument in expr.args]
        if any(sign == 0 for sign in signs):
            return 0
        if all(sign not in (None, 0) for sign in signs):
            result = 1
            for sign in signs:
                assert sign is not None
                result *= sign
            return result
        return None
    if isinstance(expr, sympy.Pow):
        base, exponent = expr.args
        base_sign = expr_sign(conditions, base)
        if exponent.is_positive is True:
            if base_sign == 0:
                return 0
            if exponent.is_Integer and exponent % 2 == 0:
                if base_sign in {-1, 1} or nonzero_implied(conditions, base):
                    return 1
                return None
            if exponent.is_Rational and exponent.q % 2 == 0:
                # An even denominator is a principal square (or higher even)
                # root: it is real and positive only on a strictly positive
                # base. Nonzero is not enough (sqrt(-2) is imaginary), and a
                # proven-negative base is not enough either, so only a strict
                # positive proof may commit to +1.
                if base_sign == 1:
                    return 1
                return None
            if base_sign is None:
                return None
            if exponent.is_Integer:
                return base_sign
            if base_sign == 1:
                return 1
        return None
    if isinstance(expr, sympy.Abs):
        argument_sign = expr_sign(conditions, expr.args[0])
        if argument_sign == 0:
            return 0
        if argument_sign in {-1, 1}:
            return 1
        if nonzero_implied(conditions, expr.args[0]):
            return 1
        return None
    if isinstance(expr, sympy.Add):
        signs = [expr_sign(conditions, argument) for argument in expr.args]
        if all(sign == 1 for sign in signs):
            return 1
        if all(sign == -1 for sign in signs):
            return -1
        return None
    if isinstance(expr, sympy.exp):
        return 1
    return None


def symbols_provably_positive(
    symbols: set[sympy.Symbol], conditions: tuple[Condition, ...]
) -> bool:
    return all(expr_sign(conditions, symbol) == 1 for symbol in symbols)


def symbols_provably_nonnegative(
    symbols: set[sympy.Symbol], conditions: tuple[Condition, ...]
) -> bool:
    for symbol in symbols:
        category = sign_category(conditions, symbol)
        if category is None or not category <= frozenset({0, 1}):
            return False
    return True


def zero_on_nonnegative_boundary(
    expr: sympy.Expr, conditions: tuple[Condition, ...]
) -> bool:
    zeroable = sorted(
        (
            symbol
            for symbol in expr.free_symbols
            if (category := sign_category(conditions, symbol)) is not None
            and 0 in category
        ),
        key=lambda symbol: symbol.name,
    )
    if len(zeroable) > 6:
        return False
    for size in range(1, len(zeroable) + 1):
        for subset in combinations(zeroable, size):
            point = {symbol: sympy.S.Zero for symbol in subset}
            try:
                restricted = sympy.sympify(expr).subs(point)
            except (TypeError, ValueError):
                return False
            if restricted.has(sympy.nan, sympy.zoo, sympy.oo, -sympy.oo):
                return False
            if not simple_zero(restricted):
                return False
    return True


def log_arguments_positive(expr: sympy.Expr, conditions: tuple[Condition, ...]) -> bool:
    arguments: list[sympy.Expr] = []

    def collect(value: sympy.Expr) -> None:
        if isinstance(value, sympy.log):
            arguments.append(value.args[0])
        for argument in value.args:
            collect(argument)

    collect(expr)
    return bool(arguments) and all(
        expr_sign(conditions, argument) == 1 for argument in arguments
    )


def nonzero_implied(conditions: tuple[Condition, ...], expr: sympy.Expr) -> bool:
    if expr.is_zero is True:
        return False
    if expr.is_nonzero is True:
        return True
    if isinstance(expr, sympy.Mul):
        return all(nonzero_implied(conditions, argument) for argument in expr.args)
    if isinstance(expr, sympy.Pow):
        base, exponent = expr.args
        if exponent.is_zero is not True:
            return nonzero_implied(conditions, base)
        return True
    if isinstance(expr, sympy.Abs):
        return nonzero_implied(conditions, expr.args[0])
    for condition in conditions:
        if condition.kind in {"ne", "gt", "lt"}:
            if same_expr(condition.expr, expr):
                return True
            if isinstance(condition.expr, sympy.Abs) and same_expr(
                condition.expr.args[0], expr
            ):
                return True
            for factor in _nonzero_factors(condition.expr):
                if same_expr(factor, expr):
                    return True
    return False


def _nonzero_factors(expr: sympy.Expr) -> tuple[sympy.Expr, ...]:
    if isinstance(expr, sympy.Mul):
        return tuple(expr.args)
    if isinstance(expr, sympy.Pow) and expr.exp.is_zero is not True:
        return (expr.base,)
    return ()
