"""Domain and exact-equivalence helpers for scalar expression checks.

The checker never samples to *accept* an identity.  It proves zero differences
with exact SymPy transformations, refines over the source domain's sign
components, and uses only exact rational witnesses to *reject* an answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Literal

import sympy
from sympy.calculus.util import continuous_domain
from sympy.solvers.inequalities import solve_univariate_inequality

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    EngineUnsupported,
)
from edcraft_validator.domains.math.ir.compile import MathCompileError, parse_exact
from edcraft_validator.domains.math.ir.schema import Expr

ConditionKind = Literal["ne", "gt", "ge", "lt", "le"]


@dataclass(frozen=True)
class Condition:
    kind: ConditionKind
    expr: sympy.Expr

    def substitute(self, values: dict[sympy.Symbol, sympy.Expr]) -> Condition:
        return Condition(self.kind, sympy.sympify(self.expr).subs(values))


@dataclass(frozen=True)
class Domain:
    conditions: tuple[Condition, ...]
    variable: sympy.Symbol | None = None
    point_set: sympy.Set | None = None


_KNOWN_AST_OPERATORS = frozenset(
    {
        "add",
        "sub",
        "mul",
        "div",
        "pow",
        "sqrt",
        "abs",
        "exp",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "log",
    }
)
_TRANSPARENT_FUNCTIONS = (sympy.exp, sympy.sin, sympy.cos, sympy.atan, sympy.Abs)
_ALL_REAL_FUNCTIONS = (sympy.sign,)


def compile_ast(ctx: EngineContext, expr: Expr | None) -> sympy.Expr:
    """Compile a validated IR node, translating compiler failures honestly."""
    if expr is None:
        raise EngineUnsupported("missing expression")
    try:
        return ctx.compile(expr)
    except (MathCompileError, TypeError, ValueError) as exc:
        raise EngineUnsupported(f"expression cannot be compiled: {exc}") from exc


def ast_conditions(ctx: EngineContext, root: Expr) -> tuple[Condition, ...]:
    """Collect the real-domain guards present in the original AST.

    Collection deliberately walks every raw denominator, square root, negative
    power, log, inverse trig and tangent node before SymPy can cancel it.
    """
    conditions: list[Condition] = []
    compiled: dict[int, sympy.Expr] = {}

    def compile_node(node: Expr) -> sympy.Expr:
        key = id(node)
        if key not in compiled:
            compiled[key] = compile_ast(ctx, node)
        return compiled[key]

    def walk(node: Expr) -> None:
        op = node.op
        if op is None:
            return
        if op not in _KNOWN_AST_OPERATORS:
            raise EngineUnsupported(f"unsupported scalar operator {op!r}")
        args = node.args
        if op == "div":
            _require_arity(op, args, 2)
            conditions.append(Condition("ne", compile_node(args[1])))
        elif op == "sqrt":
            _require_arity(op, args, 1)
            conditions.append(Condition("ge", compile_node(args[0])))
        elif op == "log":
            if len(args) == 1:
                conditions.append(Condition("gt", compile_node(args[0])))
            elif len(args) == 2:
                base = compile_node(args[1])
                conditions.append(Condition("gt", compile_node(args[0])))
                conditions.append(Condition("gt", base))
                conditions.append(Condition("ne", base - 1))
            else:
                raise EngineUnsupported("log requires one or two arguments")
        elif op == "pow":
            _require_arity(op, args, 2)
            base = compile_node(args[0])
            exponent = _compile_exponent(ctx, args[1])
            _power_conditions(base, exponent, conditions)
        elif op == "tan":
            _require_arity(op, args, 1)
            conditions.append(Condition("ne", sympy.cos(compile_node(args[0]))))
        elif op in {"asin", "acos"}:
            _require_arity(op, args, 1)
            argument = compile_node(args[0])
            conditions.append(Condition("ge", argument + 1))
            conditions.append(Condition("le", argument - 1))
        for child in args:
            walk(child)

    walk(root)
    return merge_conditions(conditions)


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
            _power_conditions(base, exponent, conditions)
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
    if left.point_set is not None and right.point_set is not None:
        point_set = left.point_set.intersect(right.point_set)
    elif left.point_set is not None:
        point_set = left.point_set
    elif right.point_set is not None:
        point_set = right.point_set
    else:
        point_set = None
    if point_set is not None and variable is not None:
        for condition in conditions:
            condition_set = _condition_set(condition, variable)
            if condition_set is None:
                point_set = None
                break
            point_set = point_set.intersect(condition_set)
    return Domain(conditions, variable, point_set)


def _as_bool(value: object) -> bool | None:
    if value is True or value is sympy.true:
        return True
    if value is False or value is sympy.false:
        return False
    return None


def domain_is_empty(domain: Domain) -> bool | None:
    if domain.point_set is not None:
        if domain.point_set is sympy.EmptySet:
            return True
        empty = _as_bool(domain.point_set.is_empty)
        if empty is not None:
            return empty
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
    point = _find_satisfying_point(ctx, domain)
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
        subset = _as_bool(source.point_set.is_subset(candidate.point_set))
        if subset is True:
            return True
        if subset is False:
            return False
        try:
            difference = source.point_set - candidate.point_set
            empty = _as_bool(difference.is_empty)
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
        if _same_expr(candidate.expr, target.expr):
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

    sign = _expr_sign(source_conditions, target.expr)
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

    if target.kind == "ne" and _nonzero_implied(source_conditions, target.expr):
        return True

    witness = _find_condition_violation(source_conditions, target, ctx)
    if witness is not None:
        return False
    return None


def provably_zero(expr: sympy.Expr, domain: Domain | None = None) -> bool:
    """Prove an expression is exactly zero on the supplied domain."""
    if _simple_zero(expr):
        return True
    if domain is not None and _symbols_provably_positive(
        expr.free_symbols, domain.conditions
    ):
        try:
            posified, _ = sympy.posify(expr)
        except (TypeError, ValueError):
            posified = expr
        if _simple_zero(posified):
            return True
    if domain is not None and _log_arguments_positive(expr, domain.conditions):
        try:
            combined = sympy.logcombine(expr, force=True)
            expanded = sympy.expand_log(expr, force=True)
        except (TypeError, ValueError):
            combined = expanded = expr
        if _simple_zero(combined) or _simple_zero(expanded):
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
        empty = _as_bool(part.is_empty)
        if empty is True:
            continue
        if empty is not False:
            return False
        checked_any = True
        try:
            refined = sympy.refine(expr, assumption)
        except (TypeError, ValueError):
            return False
        if not _simple_zero(refined):
            return False
    zero_empty = _as_bool(zero.is_empty)
    if zero_empty is not True:
        if zero_empty is not False:
            return False
        checked_any = True
        if not _value_is_zero(expr, {variable: sympy.S.Zero}):
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
    for point in _sample_points(ordered, ctx):
        if not _point_in_domain(point, domain):
            continue
        if _value_is_nonzero(expr, point):
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


def _require_arity(operator: str, args: list[Expr], arity: int) -> None:
    if len(args) != arity:
        raise EngineUnsupported(f"{operator} requires {arity} arguments")


def _compile_exponent(ctx: EngineContext, node: Expr) -> sympy.Expr:
    if node.num is not None:
        value = parse_exact(node.num)
        return sympy.Rational(value.numerator, value.denominator)
    exponent = compile_ast(ctx, node)
    if not exponent.is_number or exponent.is_real is not True:
        raise EngineUnsupported("powers require an exact real exponent")
    return exponent


def _power_conditions(
    base: sympy.Expr,
    exponent: sympy.Expr,
    conditions: list[Condition],
) -> None:
    if exponent.is_zero is True:
        return
    if exponent.is_Integer:
        if exponent < 0:
            conditions.append(Condition("ne", base))
        return
    if exponent.is_Rational:
        if exponent.q % 2 == 0:
            if exponent < 0:
                conditions.append(Condition("gt", base))
            else:
                conditions.append(Condition("ge", base))
        elif exponent < 0:
            conditions.append(Condition("ne", base))
        return
    if exponent.is_positive is True:
        conditions.append(Condition("ge", base))
    elif exponent.is_negative is True:
        conditions.append(Condition("gt", base))
    else:
        raise EngineUnsupported("cannot determine the real domain of a power")


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
    if spec.domain == "integer" or spec.integer:
        domain: sympy.Set = sympy.S.Integers
    elif spec.domain == "rational":
        domain = sympy.S.Rationals
    else:
        domain = sympy.S.Reals
    if spec.positive:
        domain = domain.intersect(sympy.Interval.open(0, sympy.oo))
    if spec.nonzero:
        domain = domain - sympy.FiniteSet(0)
    return domain


def _constant_condition_truth(condition: Condition) -> bool | None:
    if condition.kind == "ne":
        if condition.expr.is_zero is True:
            return False
        if condition.expr.is_zero is False and condition.expr.is_number:
            return True
    relation = _relation_for(condition)
    if relation is None:
        return None
    return _relational_truth(relation)


def _relational_truth(relation: sympy.Rel) -> bool | None:
    direct = _as_bool(relation)
    if direct is not None:
        return direct
    try:
        simplified = sympy.simplify(relation)
    except (TypeError, ValueError):
        simplified = relation
    return _as_bool(simplified)


def _same_condition(left: Condition, right: Condition) -> bool:
    return left.kind == right.kind and _same_expr(left.expr, right.expr)


def _same_expr(left: sympy.Expr, right: sympy.Expr) -> bool:
    if left == right:
        return True
    try:
        return sympy.simplify(left - right) == 0
    except (TypeError, ValueError):
        return False


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
        condition.kind == kind and _same_expr(condition.expr, expr)
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


def _expr_sign(conditions: tuple[Condition, ...], expr: sympy.Expr) -> int | None:
    if expr.is_zero is True:
        return 0
    if expr.is_positive is True:
        return 1
    if expr.is_negative is True:
        return -1
    for condition in conditions:
        if not _same_expr(condition.expr, expr):
            continue
        if condition.kind == "gt":
            return 1
        if condition.kind == "lt":
            return -1
    if isinstance(expr, sympy.Mul):
        signs = [_expr_sign(conditions, argument) for argument in expr.args]
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
        base_sign = _expr_sign(conditions, base)
        if exponent.is_positive is True:
            if base_sign == 0:
                return 0
            if exponent.is_Integer and exponent % 2 == 0:
                if base_sign in {-1, 1} or _nonzero_implied(conditions, base):
                    return 1
                return None
            if exponent.is_Rational and exponent.q % 2 == 0:
                if base_sign in {-1, 1} or _nonzero_implied(conditions, base):
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
        argument_sign = _expr_sign(conditions, expr.args[0])
        if argument_sign == 0:
            return 0
        if argument_sign in {-1, 1}:
            return 1
        if _nonzero_implied(conditions, expr.args[0]):
            return 1
        return None
    if isinstance(expr, sympy.Add):
        signs = [_expr_sign(conditions, argument) for argument in expr.args]
        if all(sign == 1 for sign in signs):
            return 1
        if all(sign == -1 for sign in signs):
            return -1
        return None
    if isinstance(expr, sympy.exp):
        return 1
    return None


def _symbols_provably_positive(
    symbols: set[sympy.Symbol], conditions: tuple[Condition, ...]
) -> bool:
    return all(_expr_sign(conditions, symbol) == 1 for symbol in symbols)


def _log_arguments_positive(
    expr: sympy.Expr, conditions: tuple[Condition, ...]
) -> bool:
    arguments: list[sympy.Expr] = []

    def collect(value: sympy.Expr) -> None:
        if isinstance(value, sympy.log):
            arguments.append(value.args[0])
        for argument in value.args:
            collect(argument)

    collect(expr)
    return bool(arguments) and all(
        _expr_sign(conditions, argument) == 1 for argument in arguments
    )


def _nonzero_implied(conditions: tuple[Condition, ...], expr: sympy.Expr) -> bool:
    if expr.is_zero is True:
        return False
    if expr.is_nonzero is True:
        return True
    if isinstance(expr, sympy.Mul):
        return all(_nonzero_implied(conditions, argument) for argument in expr.args)
    if isinstance(expr, sympy.Pow):
        base, exponent = expr.args
        if exponent.is_zero is not True:
            return _nonzero_implied(conditions, base)
        return True
    if isinstance(expr, sympy.Abs):
        return _nonzero_implied(conditions, expr.args[0])
    for condition in conditions:
        if condition.kind in {"ne", "gt", "lt"}:
            if _same_expr(condition.expr, expr):
                return True
            if isinstance(condition.expr, sympy.Abs) and _same_expr(
                condition.expr.args[0], expr
            ):
                return True
            for factor in _nonzero_factors(condition.expr):
                if _same_expr(factor, expr):
                    return True
    return False


def _nonzero_factors(expr: sympy.Expr) -> tuple[sympy.Expr, ...]:
    if isinstance(expr, sympy.Mul):
        return tuple(expr.args)
    if isinstance(expr, sympy.Pow) and expr.exp.is_zero is not True:
        return (expr.base,)
    return ()


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


def _sample_points(
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


def _find_satisfying_point(
    ctx: EngineContext, domain: Domain
) -> dict[sympy.Symbol, sympy.Expr] | None:
    symbols: set[sympy.Symbol] = set()
    if domain.variable is not None:
        symbols.add(domain.variable)
    for condition in domain.conditions:
        symbols.update(condition.expr.free_symbols)
    ordered = sorted(symbols, key=lambda item: item.name)
    for point in _sample_points(ordered, ctx):
        if _point_in_domain(point, domain):
            return point
    return None


def _find_condition_violation(
    source_conditions: tuple[Condition, ...],
    target: Condition,
    ctx: EngineContext,
) -> dict[sympy.Symbol, sympy.Expr] | None:
    symbols = set(target.expr.free_symbols)
    for condition in source_conditions:
        symbols.update(condition.expr.free_symbols)
    ordered = sorted(symbols, key=lambda item: item.name)
    for point in _sample_points(ordered, ctx):
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
    relation = {
        "ne": lambda: sympy.Ne(substituted, 0),
        "gt": lambda: sympy.Gt(substituted, 0),
        "ge": lambda: sympy.Ge(substituted, 0),
        "lt": lambda: sympy.Lt(substituted, 0),
        "le": lambda: sympy.Le(substituted, 0),
    }[condition.kind]()
    return _relational_truth(relation)


def _point_in_domain(point: dict[sympy.Symbol, sympy.Expr], domain: Domain) -> bool:
    if domain.point_set is not None and domain.variable is not None:
        value = point.get(domain.variable)
        if value is None:
            return False
        try:
            contains = _as_bool(domain.point_set.contains(value))
        except (TypeError, ValueError):
            contains = None
        if contains is not True:
            return False
    return all(
        _condition_truth_at(condition, point) is True for condition in domain.conditions
    )


def _value_is_zero(expr: sympy.Expr, point: dict[sympy.Symbol, sympy.Expr]) -> bool:
    value = _evaluate_exact(expr, point)
    return value is not None and value == 0


def _value_is_nonzero(expr: sympy.Expr, point: dict[sympy.Symbol, sympy.Expr]) -> bool:
    value = _evaluate_exact(expr, point)
    if value is None or value == 0:
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


def _simple_zero(expr: sympy.Expr) -> bool:
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
