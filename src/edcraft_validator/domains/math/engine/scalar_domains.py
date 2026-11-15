"""Domain and exact-equivalence helpers for scalar expression checks.

The checker never samples to *accept* an identity.  It proves zero differences
with exact SymPy transformations, refines over the source domain's sign
components, and uses only exact rational witnesses to *reject* an answer.
"""

from __future__ import annotations

from dataclasses import dataclass

import sympy
from sympy.calculus.util import continuous_domain
from sympy.solvers.inequalities import solve_univariate_inequality

from edcraft_validator.domains.math.engine.conditions import (
    Condition,
    ConditionKind,
    ast_conditions,
    power_conditions,
    symbol_domain,
)
from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import EngineUnsupported
from edcraft_validator.domains.math.engine.scalar_sampling import (
    as_bool,
    find_condition_violation,
    find_satisfying_point,
    point_in_domain,
    relational_truth,
    sample_points,
    simple_zero,
    value_is_nonzero,
    value_is_zero,
)
from edcraft_validator.domains.math.engine.scalar_signs import (
    expr_sign,
    log_arguments_positive,
    nonzero_implied,
    same_expr,
    sign_category,
    symbols_provably_nonnegative,
    symbols_provably_positive,
    zero_on_nonnegative_boundary,
)
from edcraft_validator.domains.math.ir.schema import Expr


@dataclass(frozen=True)
class Domain:
    conditions: tuple[Condition, ...]
    variable: sympy.Symbol | None = None
    point_set: sympy.Set | None = None


_TRANSPARENT_FUNCTIONS = (sympy.exp, sympy.sin, sympy.cos, sympy.atan, sympy.Abs)
_ALL_REAL_FUNCTIONS = (sympy.sign,)


def sympy_conditions(root: sympy.Expr) -> tuple[Condition, ...]:
    """Collect real-domain guards directly from an expected SymPy expression."""
    conditions: list[Condition] = []
    seen: set[int] = set()

    def walk(expr: sympy.Expr) -> None:
        if expr in (sympy.true, sympy.false) or expr.is_Atom:
            return
        key = id(expr)
        if key in seen:
            return
        seen.add(key)
        if isinstance(expr, (sympy.Add, sympy.Mul)):
            for argument in expr.args:
                walk(argument)
            return
        if isinstance(expr, sympy.Pow):
            base, exponent = expr.args
            power_conditions(base, exponent, conditions)
            walk(base)
            walk(exponent)
            return
        if isinstance(expr, sympy.log):
            conditions.append(Condition("gt", expr.args[0]))
            for argument in expr.args:
                walk(argument)
            return
        if isinstance(expr, sympy.tan):
            conditions.append(Condition("ne", sympy.cos(expr.args[0])))
            walk(expr.args[0])
            return
        if isinstance(expr, (sympy.asin, sympy.acos)):
            argument = expr.args[0]
            conditions.append(Condition("ge", argument + 1))
            conditions.append(Condition("le", argument - 1))
            walk(argument)
            return
        if isinstance(expr, _TRANSPARENT_FUNCTIONS + _ALL_REAL_FUNCTIONS):
            for argument in expr.args:
                walk(argument)
            return
        if isinstance(expr, sympy.Function):
            raise EngineUnsupported(
                f"cannot determine the real domain of {type(expr).__name__}"
            )
        for argument in expr.args:
            walk(argument)

    walk(root)
    return merge_conditions(conditions)


def domain_from_conditions(
    ctx: EngineContext,
    compiled: sympy.Expr,
    conditions: tuple[Condition, ...],
    variable: sympy.Symbol | None = None,
) -> Domain:
    """Build a domain from explicit guards and the compiled expression."""
    conditions = merge_conditions(conditions)
    chosen = variable
    if chosen is None:
        symbols = set(compiled.free_symbols)
        for condition in conditions:
            symbols.update(condition.expr.free_symbols)
        if len(symbols) == 1:
            chosen = next(iter(symbols))
    point_set = _point_set(ctx, compiled, conditions, chosen)
    return Domain(conditions, chosen, point_set)


def ast_domain(
    ctx: EngineContext,
    ast: Expr,
    compiled: sympy.Expr,
    variable: sympy.Symbol | None = None,
    extra: tuple[Condition, ...] = (),
) -> Domain:
    return domain_from_conditions(
        ctx,
        compiled,
        merge_conditions(extra + ast_conditions(ctx, ast)),
        variable,
    )


def sympy_domain(
    ctx: EngineContext,
    compiled: sympy.Expr,
    variable: sympy.Symbol | None = None,
) -> Domain:
    return domain_from_conditions(ctx, compiled, sympy_conditions(compiled), variable)


def intersect_domains(left: Domain, right: Domain) -> Domain:
    conditions = merge_conditions(left.conditions + right.conditions)
    variable = left.variable if left.variable is not None else right.variable
    point_set: sympy.Set | None
    missing: tuple[Condition, ...] = ()
    if left.point_set is not None and right.point_set is not None:
        point_set = (
            left.point_set
            if left.point_set.dummy_eq(right.point_set)
            else left.point_set.intersect(right.point_set)
        )
    elif left.point_set is not None:
        point_set, missing = left.point_set, right.conditions
    elif right.point_set is not None:
        point_set, missing = right.point_set, left.conditions
    else:
        point_set = None
    # A resolved point set already incorporates its own guards. Re-applying
    # periodic exclusions repeatedly can make equivalent ImageSets explode.
    if point_set is not None and variable is not None:
        for condition in missing:
            condition_set = _condition_set(condition, variable)
            if condition_set is None:
                point_set = None
                break
            point_set = point_set.intersect(condition_set)
    return Domain(conditions, variable, point_set)


def _countable_set(points: sympy.Set) -> bool:
    if isinstance(points, sympy.FiniteSet) or points is sympy.EmptySet:
        return True
    if isinstance(points, sympy.Union):
        return all(_countable_set(part) for part in points.args)
    if isinstance(points, sympy.ImageSet):
        return all(
            base in (sympy.S.Integers, sympy.S.Naturals, sympy.S.Naturals0)
            for base in points.base_sets
        )
    return False


def domain_is_empty(domain: Domain) -> bool | None:
    if domain.point_set is not None:
        if domain.point_set is sympy.EmptySet:
            return True
        empty = as_bool(domain.point_set.is_empty)
        if empty is not None:
            return empty
        if isinstance(domain.point_set, sympy.Complement):
            base, excluded = domain.point_set.args
            # Removing countably many periodic poles/zeros cannot empty a
            # real interval of positive length. No sample agreement is used.
            if (
                base is sympy.S.Reals
                or isinstance(base, sympy.Interval)
                and base.measure.is_positive is True
            ) and _countable_set(excluded):
                return False
    for condition in domain.conditions:
        truth = _constant_condition_truth(condition)
        if truth is False:
            return True
    return None


def domain_nonempty(ctx: EngineContext, domain: Domain) -> bool | None:
    empty = domain_is_empty(domain)
    if empty is True:
        return False
    if empty is False:
        return True
    if not domain.conditions:
        return True
    point = find_satisfying_point(ctx, domain)
    if point is not None:
        return True
    return None


def domain_covered(
    source: Domain,
    candidate: Domain,
    ctx: EngineContext,
) -> bool | None:
    """Return whether the candidate is defined everywhere the source is."""
    if source.point_set is not None and candidate.point_set is not None:
        if source.point_set.dummy_eq(candidate.point_set):
            return True
        subset = as_bool(source.point_set.is_subset(candidate.point_set))
        if subset is True:
            return True
        if subset is False:
            return False
        try:
            difference = source.point_set - candidate.point_set
            empty = as_bool(difference.is_empty)
            if difference is sympy.EmptySet or empty is True:
                return True
            if empty is False:
                return False
        except (TypeError, ValueError):
            pass
    result: bool | None = True
    for condition in candidate.conditions:
        implied = condition_implied(source.conditions, condition, ctx)
        if implied is False:
            return False
        if implied is None:
            result = None
    return result


def condition_implied(
    source_conditions: tuple[Condition, ...],
    target: Condition,
    ctx: EngineContext,
) -> bool | None:
    for candidate in source_conditions:
        if _same_condition(candidate, target):
            return True
        if same_expr(candidate.expr, target.expr):
            if candidate.kind == target.kind:
                return True
            if target.kind in _IMPLIED_KINDS[candidate.kind]:
                return True
    if _has_condition(source_conditions, "ge", target.expr) and _has_condition(
        source_conditions, "ne", target.expr
    ):
        if target.kind == "gt":
            return True
    if _has_condition(source_conditions, "le", target.expr) and _has_condition(
        source_conditions, "ne", target.expr
    ):
        if target.kind == "lt":
            return True

    assumed = _assumption_truth(target)
    if assumed is True:
        return True
    if assumed is False:
        return False

    sign = expr_sign(source_conditions, target.expr)
    if target.kind == "gt" and sign == 1:
        return True
    if target.kind == "ge" and sign in {0, 1}:
        return True
    if target.kind == "lt" and sign == -1:
        return True
    if target.kind == "le" and sign in {-1, 0}:
        return True
    if target.kind == "ne" and sign in {-1, 1}:
        return True
    if target.kind in {"gt", "ge"} and sign == -1:
        return False
    if target.kind in {"lt", "le"} and sign == 1:
        return False

    # ``expr_sign`` only commits to a single sign. Non-strict guards such as
    # ``ge``/``le`` describe a *set* of possible signs, and products of such
    # quantities (``sqrt(x)*sqrt(y)``) are nonnegative without being positive.
    category = sign_category(source_conditions, target.expr)
    if category is not None:
        if target.kind == "gt" and category == frozenset({1}):
            return True
        if target.kind == "ge" and category <= frozenset({0, 1}):
            return True
        if target.kind == "lt" and category == frozenset({-1}):
            return True
        if target.kind == "le" and category <= frozenset({-1, 0}):
            return True
        if target.kind == "ne" and 0 not in category:
            return True

    if target.kind == "ne" and nonzero_implied(source_conditions, target.expr):
        return True

    witness = find_condition_violation(source_conditions, target, ctx)
    if witness is not None:
        return False
    return None


def provably_zero(expr: sympy.Expr, domain: Domain | None = None) -> bool:
    """Prove an expression is exactly zero on the supplied domain."""
    if simple_zero(expr):
        return True
    if domain is not None:
        # On a domain excluding f=0, sign(f)=f/Abs(f) for real f.
        substitutions = {
            term: term.args[0] / sympy.Abs(term.args[0])
            for term in expr.atoms(sympy.sign)
            if term.args[0].is_real is True
            and nonzero_implied(domain.conditions, term.args[0])
        }
        if substitutions and simple_zero(expr.xreplace(substitutions)):
            return True
    if domain is not None and symbols_provably_positive(
        expr.free_symbols, domain.conditions
    ):
        try:
            posified, _ = sympy.posify(expr)
        except (TypeError, ValueError):
            posified = expr
        if simple_zero(posified):
            return True
    if domain is not None and symbols_provably_nonnegative(
        expr.free_symbols, domain.conditions
    ):
        # ``posify`` proves the identity on the open positive orthant. The
        # remaining boundary points (where a nonnegative symbol is zero) are
        # checked exactly, which covers the whole closed domain.
        try:
            posified, _ = sympy.posify(expr)
        except (TypeError, ValueError):
            posified = expr
        if simple_zero(posified) and zero_on_nonnegative_boundary(
            expr, domain.conditions
        ):
            return True
    if domain is not None and log_arguments_positive(expr, domain.conditions):
        try:
            combined = sympy.logcombine(expr, force=True)
            expanded = sympy.expand_log(expr, force=True)
        except (TypeError, ValueError):
            combined = expanded = expr
        if simple_zero(combined) or simple_zero(expanded):
            return True
    if domain is None or domain.variable is None or domain.point_set is None:
        return False
    variable = domain.variable
    if not expr.free_symbols <= {variable}:
        return False
    positive = domain.point_set.intersect(sympy.Interval.open(0, sympy.oo))
    negative = domain.point_set.intersect(sympy.Interval.open(-sympy.oo, 0))
    zero = domain.point_set.intersect(sympy.FiniteSet(0))
    checked_any = False
    for part, assumption in (
        (positive, sympy.Q.positive(variable)),
        (negative, sympy.Q.negative(variable)),
    ):
        empty = as_bool(part.is_empty)
        if empty is True:
            continue
        if empty is not False:
            return False
        checked_any = True
        try:
            refined = sympy.refine(expr, assumption)
        except (TypeError, ValueError):
            return False
        if not simple_zero(refined):
            return False
    zero_empty = as_bool(zero.is_empty)
    if zero_empty is not True:
        if zero_empty is not False:
            return False
        checked_any = True
        if not value_is_zero(expr, {variable: sympy.S.Zero}):
            return False
    return checked_any


def counterexample(
    expr: sympy.Expr,
    domain: Domain,
    ctx: EngineContext,
    extra_symbols: set[sympy.Symbol] | None = None,
) -> dict[str, sympy.Expr] | None:
    """Find an exact rational point in the domain where ``expr`` is nonzero."""
    symbols = set(expr.free_symbols)
    if extra_symbols:
        symbols.update(extra_symbols)
    for condition in domain.conditions:
        symbols.update(condition.expr.free_symbols)
    if domain.variable is not None:
        symbols.add(domain.variable)
    ordered = sorted(symbols, key=lambda item: item.name)
    for point in sample_points(ordered, ctx):
        if not point_in_domain(point, domain):
            continue
        if value_is_nonzero(expr, point):
            return {symbol.name: value for symbol, value in point.items()}
    return None


def merge_conditions(
    conditions: tuple[Condition, ...] | list[Condition],
) -> tuple[Condition, ...]:
    merged: list[Condition] = []
    for condition in conditions:
        if not any(_same_condition(condition, existing) for existing in merged):
            merged.append(condition)
    return tuple(merged)


def _point_set(
    ctx: EngineContext,
    compiled: sympy.Expr,
    conditions: tuple[Condition, ...],
    variable: sympy.Symbol | None,
) -> sympy.Set | None:
    if variable is None:
        if not compiled.free_symbols and not any(
            condition.expr.free_symbols for condition in conditions
        ):
            for condition in conditions:
                truth = _constant_condition_truth(condition)
                if truth is False:
                    return sympy.EmptySet
                if truth is None:
                    return None
            return sympy.S.Reals
        return None
    symbols = set(compiled.free_symbols)
    for condition in conditions:
        symbols.update(condition.expr.free_symbols)
    if not symbols <= {variable}:
        return None
    point_set = _symbol_domain(ctx, variable)
    try:
        continuous = continuous_domain(compiled, variable, sympy.S.Reals)
    except (NotImplementedError, TypeError, ValueError):
        continuous = None
    if (
        continuous is not None
        and not isinstance(continuous, sympy.ConditionSet)
        and not continuous.has(sympy.ConditionSet)
    ):
        point_set = point_set.intersect(continuous)
    for condition in conditions:
        condition_set = _condition_set(condition, variable)
        if condition_set is None:
            return None
        if not point_set.dummy_eq(condition_set):
            point_set = point_set.intersect(condition_set)
    return point_set


def _condition_set(condition: Condition, variable: sympy.Symbol) -> sympy.Set | None:
    # SymPy's inequality helper may return a single period. That cannot stand
    # for the complete real domain of log(sin(x)), square roots of trig, etc.
    if condition.kind != "ne" and any(
        atom.has(variable)
        for atom in condition.expr.atoms(sympy.sin, sympy.cos, sympy.tan)
    ):
        return None
    if not condition.expr.free_symbols <= {variable}:
        return None
    if not condition.expr.free_symbols:
        truth = _constant_condition_truth(condition)
        if truth is None:
            return None
        return sympy.S.Reals if truth else sympy.EmptySet
    if condition.kind == "ne":
        try:
            zeros = sympy.solveset(condition.expr, variable, domain=sympy.S.Reals)
        except (NotImplementedError, TypeError, ValueError):
            zeros = None
        if (
            zeros is not None
            and not isinstance(zeros, sympy.ConditionSet)
            and not zeros.has(sympy.ConditionSet)
        ):
            if zeros is sympy.S.Reals:
                return sympy.EmptySet
            return sympy.S.Reals - zeros
    relation = _relation_for(condition)
    if relation is None:
        return None
    try:
        result = solve_univariate_inequality(relation, variable, relational=False)
    except (NotImplementedError, TypeError, ValueError):
        return None
    if isinstance(result, sympy.ConditionSet) or result.has(sympy.ConditionSet):
        return None
    return result


def _relation_for(condition: Condition) -> sympy.Rel | None:
    zero = sympy.S.Zero
    return {
        "ne": lambda: sympy.Ne(condition.expr, zero),
        "gt": lambda: sympy.Gt(condition.expr, zero),
        "ge": lambda: sympy.Ge(condition.expr, zero),
        "lt": lambda: sympy.Lt(condition.expr, zero),
        "le": lambda: sympy.Le(condition.expr, zero),
    }[condition.kind]()


def _symbol_domain(ctx: EngineContext, symbol: sympy.Symbol) -> sympy.Set:
    spec = next(
        (item for item in ctx.request.problem.symbols if item.name == symbol.name),
        None,
    )
    if spec is None:
        return sympy.S.Reals
    return symbol_domain(spec)


def _constant_condition_truth(condition: Condition) -> bool | None:
    if condition.kind == "ne":
        if condition.expr.is_zero is True:
            return False
        if condition.expr.is_zero is False and condition.expr.is_number:
            return True
    relation = _relation_for(condition)
    if relation is None:
        return None
    return relational_truth(relation)


def _same_condition(left: Condition, right: Condition) -> bool:
    return left.kind == right.kind and same_expr(left.expr, right.expr)


_IMPLIED_KINDS: dict[ConditionKind, frozenset[ConditionKind]] = {
    "gt": frozenset({"gt", "ge", "ne"}),
    "ge": frozenset({"ge"}),
    "lt": frozenset({"lt", "le", "ne"}),
    "le": frozenset({"le"}),
    "ne": frozenset({"ne"}),
}


def _has_condition(
    conditions: tuple[Condition, ...], kind: ConditionKind, expr: sympy.Expr
) -> bool:
    return any(
        condition.kind == kind and same_expr(condition.expr, expr)
        for condition in conditions
    )


def _assumption_truth(condition: Condition) -> bool | None:
    expr = condition.expr
    flags = {
        "ne": "is_nonzero",
        "gt": "is_positive",
        "ge": "is_nonnegative",
        "lt": "is_negative",
        "le": "is_nonpositive",
    }
    value = getattr(expr, flags[condition.kind], None)
    if value is True:
        return True
    if value is False:
        return False
    if condition.kind == "ne":
        if expr.is_zero is True:
            return False
        if expr.is_zero is False:
            return True
    return None
