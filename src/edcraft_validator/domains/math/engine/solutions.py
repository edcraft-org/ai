"""Deterministic solution-set correctness for one variable and linear systems.

The complete solution set is computed from every original relation.  Domain
constraints are read from the original expression tree *before* SymPy has a
chance to cancel denominators or turn a relation into ``True``.  Candidate
answers are only accepted when exact set operations prove equality; unresolved
membership is reported as unknown rather than being discarded.
"""

from __future__ import annotations

import sympy
from sympy.solvers.inequalities import solve_univariate_inequality

from edcraft_validator.domains.math.engine.conditions import (
    Condition as _Condition,
)
from edcraft_validator.domains.math.engine.conditions import (
    ast_conditions,
    symbol_domain,
)
from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessResult,
    EngineUnknown,
    EngineUnsupported,
    MathAnswer,
    MathProblem,
)
from edcraft_validator.domains.math.ir.schema import Expr, Relation, SymbolSpec

_DOMAINS = {
    "real": sympy.S.Reals,
    "integer": sympy.S.Integers,
    "rational": sympy.S.Rationals,
}
_RELATIONS = {
    "eq": sympy.Eq,
    "ne": sympy.Ne,
    "lt": sympy.Lt,
    "le": sympy.Le,
    "gt": sympy.Gt,
    "ge": sympy.Ge,
}
_ALLOWED_FUNCTIONS = (
    sympy.exp,
    sympy.log,
    sympy.sin,
    sympy.cos,
    sympy.tan,
    sympy.asin,
    sympy.acos,
    sympy.atan,
    sympy.Abs,
)
_PERIODIC_FUNCTIONS = (sympy.sin, sympy.cos, sympy.tan)


class _CandidateIncorrect(Exception):
    """The candidate makes a definite mathematical mistake."""


def check_solutions(ctx: EngineContext) -> CorrectnessResult:
    """Check a ``solve`` answer against the complete solution set."""
    problem = ctx.request.problem
    if problem.operation != "solve":
        raise EngineUnsupported("check_solutions only handles solve problems")
    if not problem.solve_for:
        raise EngineUnsupported("solve problems require at least one target symbol")
    if len(problem.solve_for) == 1:
        return _check_univariate(ctx)
    return _check_linear_system(ctx)


# ---------------------------------------------------------------------------
# Shared helpers


def _symbol_spec(problem: MathProblem, name: str) -> SymbolSpec:
    for spec in problem.symbols:
        if spec.name == name:
            return spec
    raise EngineUnsupported(f"target symbol {name!r} has no declaration")


def _compiled_relations(
    ctx: EngineContext,
) -> list[tuple[Relation, sympy.Expr, sympy.Expr]]:
    return [
        (relation, ctx.compile(relation.lhs), ctx.compile(relation.rhs))
        for relation in ctx.request.problem.relations
    ]


def _compile_relation(kind: str, lhs: sympy.Expr, rhs: sympy.Expr) -> sympy.Rel:
    return _RELATIONS[kind](lhs, rhs)


def _is_true(value: object) -> bool:
    return value is sympy.true or value is True


def _is_false(value: object) -> bool:
    return value is sympy.false or value is False


def _ensure_set_supported(value: sympy.Set) -> None:
    """Reject set shapes that cannot be a complete representable solution."""
    if value is sympy.EmptySet:
        return
    if value is sympy.S.Reals or value is sympy.S.Integers:
        return
    if value is sympy.S.Rationals:
        return
    if isinstance(value, sympy.ConditionSet):
        raise EngineUnknown("the solver returned an undecided condition set")
    if isinstance(value, sympy.ImageSet):
        raise EngineUnsupported("periodic solution sets are not representable")
    if isinstance(value, sympy.FiniteSet):
        for item in value.args:
            _ensure_representable_number(item)
        return
    if isinstance(value, sympy.Interval):
        for endpoint in (value.start, value.end):
            if endpoint is sympy.S.NegativeInfinity or endpoint is sympy.S.Infinity:
                continue
            _ensure_representable_number(endpoint)
        return
    if isinstance(value, (sympy.Union, sympy.Intersection)):
        for argument in value.args:
            _ensure_set_supported(argument)
        return
    if isinstance(value, sympy.Complement):
        for argument in value.args:
            _ensure_set_supported(argument)
        return
    if isinstance(value, sympy.Range):
        for endpoint in (value.start, value.stop, value.step):
            if endpoint is sympy.S.NegativeInfinity or endpoint is sympy.S.Infinity:
                continue
            _ensure_representable_number(endpoint)
        return
    if value is sympy.S.Complexes:
        raise EngineUnsupported("non-real solution sets are unsupported")
    raise EngineUnsupported(f"unsupported solution set shape {type(value).__name__}")


def _ensure_representable_number(value: object) -> None:
    if not isinstance(value, sympy.Expr):
        raise EngineUnsupported("solution components must be scalar expressions")
    if value.has(sympy.ConditionSet):
        raise EngineUnknown("a solution component contains a condition set")
    if value.has(sympy.ImageSet):
        raise EngineUnsupported("periodic solution components are unsupported")
    if value.has(sympy.CRootOf, sympy.RootOf, sympy.RootSum):
        raise EngineUnsupported(
            "the complete roots are not representable using the closed expression IR"
        )
    if value.has(sympy.Integral, sympy.Derivative, sympy.Limit):
        raise EngineUnsupported("unevaluated symbolic operators are unsupported")
    for function in value.atoms(sympy.Function):
        if not isinstance(function, _ALLOWED_FUNCTIONS):
            raise EngineUnsupported(
                f"solution function {type(function).__name__} is unsupported"
            )


def _solve_relation(
    kind: str,
    lhs: sympy.Expr,
    rhs: sympy.Expr,
    variable: sympy.Symbol,
    domain: str,
) -> sympy.Set:
    relation = _compile_relation(kind, lhs, rhs)
    if _is_true(relation):
        return _DOMAINS[domain]
    if _is_false(relation):
        return sympy.EmptySet
    try:
        if kind in {"eq", "ne"}:
            solution = sympy.solveset(relation, variable, domain=_DOMAINS[domain])
        else:
            solution = solve_univariate_inequality(
                relation, variable, relational=False, domain=_DOMAINS[domain]
            )
    except (EngineUnknown, EngineUnsupported):
        raise
    except Exception as exc:  # SymPy raises several solver-specific exceptions
        raise EngineUnsupported(
            "the deterministic solver could not settle this relation"
        ) from exc
    _ensure_set_supported(solution)
    complete_all_domain = (
        solution is sympy.S.Reals
        or solution is sympy.S.Integers
        or solution is sympy.S.Rationals
    )
    if (lhs.has(*_PERIODIC_FUNCTIONS) or rhs.has(*_PERIODIC_FUNCTIONS)) and not (
        solution is sympy.EmptySet
        or complete_all_domain
        or isinstance(solution, sympy.FiniteSet)
    ):
        raise EngineUnsupported(
            "the periodic solution set cannot be represented completely"
        )
    return solution


def _intersect(left: sympy.Set, right: sympy.Set) -> sympy.Set:
    try:
        return left.intersect(right)
    except (EngineUnknown, EngineUnsupported):
        raise
    except Exception as exc:
        raise EngineUnknown("the solution intersection could not be evaluated") from exc


# ---------------------------------------------------------------------------
# Original-tree domain constraints


def _condition_set(
    condition: _Condition, variable: sympy.Symbol, domain: str
) -> sympy.Set:
    expression = condition.expr
    if condition.kind == "ne":
        if expression.is_zero is True:
            return sympy.EmptySet
        if expression.is_zero is False:
            return _DOMAINS[domain]
        zeroes = _solve_relation("eq", expression, sympy.Integer(0), variable, domain)
        if zeroes is sympy.EmptySet:
            return _DOMAINS[domain]
        try:
            return _DOMAINS[domain] - zeroes
        except (EngineUnknown, EngineUnsupported):
            raise
        except Exception as exc:
            raise EngineUnknown(
                "a denominator exclusion could not be evaluated"
            ) from exc
    relation = _compile_relation(condition.kind, expression, sympy.Integer(0))
    if _is_true(relation):
        return _DOMAINS[domain]
    if _is_false(relation):
        return sympy.EmptySet
    try:
        solution = solve_univariate_inequality(
            relation, variable, relational=False, domain=_DOMAINS[domain]
        )
    except (EngineUnknown, EngineUnsupported):
        raise
    except Exception as exc:
        raise EngineUnsupported(
            "a source domain restriction could not be evaluated"
        ) from exc
    _ensure_set_supported(solution)
    return solution


# ---------------------------------------------------------------------------
# Candidate answers


def _compile_answer_expr(ctx: EngineContext, expr: Expr | None) -> sympy.Expr:
    if expr is None:
        raise EngineUnsupported("the answer is missing an expression")
    return ctx.compile(expr)


def _validate_number(value: sympy.Expr, description: str) -> None:
    if value.free_symbols:
        raise EngineUnknown(
            f"{description} contains an unresolved symbol; membership is undecidable"
        )
    if value in (sympy.nan, sympy.zoo, sympy.oo, -sympy.oo):
        raise _CandidateIncorrect(f"{description} is not a finite real number")
    if value.is_finite is False:
        raise _CandidateIncorrect(f"{description} is not finite")
    if value.is_real is False:
        raise _CandidateIncorrect(f"{description} is not real")
    if value.is_real is None:
        raise EngineUnknown(f"whether {description} is real cannot be determined")


def _membership(value: sympy.Expr, spec: SymbolSpec, domain: str) -> bool | None:
    """Tri-state membership in the requested and declared domain."""
    if value.is_real is False:
        return False
    if value.is_real is None:
        return None
    if domain == "integer" or spec.domain == "integer" or spec.integer:
        if value.is_integer is not True:
            return value.is_integer
    if domain == "rational" or spec.domain == "rational":
        if value.is_rational is not True:
            return value.is_rational
    if spec.positive and value.is_positive is not True:
        return value.is_positive
    if spec.nonzero and value.is_zero is not False:
        return None if value.is_zero is None else False
    return True


def _validate_membership(value: sympy.Expr, spec: SymbolSpec, domain: str) -> None:
    state = _membership(value, spec, domain)
    if state is False:
        raise _CandidateIncorrect(
            "a candidate value lies outside the declared solution domain"
        )
    if state is None:
        raise EngineUnknown("candidate domain membership cannot be determined")


def _evaluate_condition(
    condition: _Condition, substitutions: dict[sympy.Symbol, sympy.Expr]
) -> bool | None:
    expression = condition.expr.subs(substitutions)
    if expression.free_symbols:
        return None
    if condition.kind == "ne":
        if expression == 0 or expression.is_zero is True:
            return False
        if expression.is_zero is False:
            return True
        return None
    relation = _compile_relation(condition.kind, expression, sympy.Integer(0))
    if _is_true(relation):
        return True
    if _is_false(relation):
        return False
    return None


def _validate_point_conditions(
    value: sympy.Expr,
    variable: sympy.Symbol,
    conditions: list[_Condition],
) -> None:
    for condition in conditions:
        truth = _evaluate_condition(condition, {variable: value})
        if truth is False:
            raise _CandidateIncorrect(
                "a candidate value violates an original domain restriction"
            )
        if truth is None:
            raise EngineUnknown(
                "candidate membership in the source domain is undecidable"
            )


def _validate_point(
    value: sympy.Expr,
    variable: sympy.Symbol,
    spec: SymbolSpec,
    domain: str,
    conditions: list[_Condition],
) -> None:
    _validate_number(value, "a candidate value")
    _validate_membership(value, spec, domain)
    _validate_point_conditions(value, variable, conditions)


def _validate_endpoint(value: sympy.Expr | None) -> sympy.Expr | None:
    if value is None:
        return None
    _validate_number(value, "a candidate interval endpoint")
    return value


def _compare_endpoints(left: sympy.Expr | None, right: sympy.Expr | None) -> int | None:
    if left is None and right is None:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    difference = sympy.simplify(left - right)
    if difference == 0 or difference.is_zero is True:
        return 0
    if difference.is_positive is True:
        return 1
    if difference.is_negative is True:
        return -1
    return None


def _validate_interval_order(
    lower: sympy.Expr | None, upper: sympy.Expr | None
) -> None:
    if lower is None or upper is None:
        return
    comparison = _compare_endpoints(lower, upper)
    if comparison is None:
        raise EngineUnknown("the order of two interval endpoints is undecidable")
    if comparison > 0:
        raise _CandidateIncorrect("a candidate interval has reversed endpoints")


def _candidate_set(
    ctx: EngineContext,
    variable: sympy.Symbol,
    spec: SymbolSpec,
    domain: str,
    conditions: list[_Condition],
) -> sympy.Set:
    answer: MathAnswer = ctx.request.answer
    if answer.kind == "expression":
        value = _compile_answer_expr(ctx, answer.expression)
        _validate_point(value, variable, spec, domain, conditions)
        return sympy.FiniteSet(value)
    if answer.kind != "set":
        raise EngineUnsupported(
            "one-variable solution answers must use the set or expression kind"
        )

    points: list[sympy.Expr] = []
    for item in answer.items:
        value = ctx.compile(item)
        _validate_point(value, variable, spec, domain, conditions)
        points.append(value)

    intervals: list[sympy.Set] = []
    for bounds in answer.intervals:
        lower = _validate_endpoint(
            None if bounds.lower is None else ctx.compile(bounds.lower)
        )
        upper = _validate_endpoint(
            None if bounds.upper is None else ctx.compile(bounds.upper)
        )
        _validate_interval_order(lower, upper)
        intervals.append(
            sympy.Interval(
                sympy.S.NegativeInfinity if lower is None else lower,
                sympy.S.Infinity if upper is None else upper,
                left_open=bounds.lower_open,
                right_open=bounds.upper_open,
            )
        )

    parts: list[sympy.Set] = list(intervals)
    if points:
        parts.insert(0, sympy.FiniteSet(*points))
    if not parts:
        return sympy.EmptySet
    return sympy.Union(*parts)


def _simplify_set(value: sympy.Set) -> sympy.Set:
    """Apply the small complement identities SymPy leaves unevaluated."""
    if isinstance(value, sympy.Complement):
        base, removed = value.args
        removed = _simplify_set(removed)
        if removed is sympy.EmptySet:
            return base
        if base == removed:
            return sympy.EmptySet
        if isinstance(removed, sympy.Complement):
            inner_base, inner_removed = removed.args
            if inner_base == base:
                return sympy.Intersection(inner_removed, base)
        return sympy.Complement(base, removed)
    if isinstance(value, sympy.Union):
        return sympy.Union(*[_simplify_set(argument) for argument in value.args])
    if isinstance(value, sympy.Intersection):
        return sympy.Intersection(*[_simplify_set(argument) for argument in value.args])
    return value


def _sets_equal(expected: sympy.Set, candidate: sympy.Set) -> bool:
    expected_finite = expected.is_finite_set
    candidate_finite = candidate.is_finite_set
    if expected_finite is True and candidate_finite is False:
        return False
    if expected_finite is False and candidate_finite is True:
        return False
    try:
        difference = expected.symmetric_difference(candidate)
    except (EngineUnknown, EngineUnsupported):
        raise
    except Exception as exc:
        raise EngineUnknown("solution sets could not be compared") from exc
    difference = _simplify_set(difference)
    if difference == sympy.EmptySet or difference.is_empty is True:
        return True
    if difference.is_empty is False:
        return False
    simplified = _simplify_set(sympy.simplify(difference))
    if simplified == sympy.EmptySet or simplified.is_empty is True:
        return True
    if simplified.is_empty is False:
        return False
    # Exact witnesses can disprove equality when symbolic set reduction stalls.
    # Agreement at these points is never sufficient to accept an answer.
    for point in map(sympy.Rational, (0, 1, -1, "1/2", "-1/2", "1/3", "4/3", 2)):
        wanted = expected.contains(point)
        supplied = candidate.contains(point)
        if (
            wanted in (sympy.true, sympy.false)
            and supplied
            in (
                sympy.true,
                sympy.false,
            )
            and wanted != supplied
        ):
            return False
    raise EngineUnknown("whether the answer set equals the solution set is undecidable")


# ---------------------------------------------------------------------------
# One-variable solving


def _check_univariate(ctx: EngineContext) -> CorrectnessResult:
    problem = ctx.request.problem
    name = problem.solve_for[0]
    variable = ctx.symbols[name]
    spec = _symbol_spec(problem, name)
    compiled = _compiled_relations(ctx)

    for _relation, lhs, rhs in compiled:
        extra = (lhs.free_symbols | rhs.free_symbols) - {variable}
        if extra:
            raise EngineUnsupported(
                "symbolic parameters in a one-variable equation are unsupported"
            )

    base = symbol_domain(spec, problem.domain)
    expected = base
    for relation, lhs, rhs in compiled:
        expected = _intersect(
            expected,
            _solve_relation(relation.kind, lhs, rhs, variable, problem.domain),
        )

    conditions: list[_Condition] = []
    for relation in problem.relations:
        conditions.extend(ast_conditions(ctx, relation.lhs))
        conditions.extend(ast_conditions(ctx, relation.rhs))
    if expected is not sympy.EmptySet:
        for condition in conditions:
            expected = _intersect(
                expected, _condition_set(condition, variable, problem.domain)
            )
    _ensure_set_supported(expected)

    try:
        candidate = _candidate_set(ctx, variable, spec, problem.domain, conditions)
        effective = _intersect(candidate, base)
        matches = _sets_equal(expected, effective)
    except _CandidateIncorrect:
        return _incorrect_result(ctx, expected, "a candidate value is not admissible")
    if matches:
        return ctx.result(
            "correct",
            "the answer set equals the complete solution set on the declared domain",
            "solveset+domain-intersection",
            domain=problem.domain,
            relation_count=len(problem.relations),
            expected=sympy.sstr(expected),
        )
    return _incorrect_result(ctx, expected, "the answer set is incomplete or differs")


def _incorrect_result(
    ctx: EngineContext, expected: sympy.Set, reason: str
) -> CorrectnessResult:
    return ctx.result(
        "incorrect",
        reason,
        "solveset+domain-intersection",
        domain=ctx.request.problem.domain,
        relation_count=len(ctx.request.problem.relations),
        expected=sympy.sstr(expected),
    )


# ---------------------------------------------------------------------------
# Linear systems


def _check_linear_system(ctx: EngineContext) -> CorrectnessResult:
    problem = ctx.request.problem
    names = problem.solve_for
    variables = [ctx.symbols[name] for name in names]
    specs = [_symbol_spec(problem, name) for name in names]
    compiled = _compiled_relations(ctx)

    for relation, _lhs, _rhs in compiled:
        if relation.kind != "eq":
            raise EngineUnsupported(
                "multi-symbol solving supports linear equalities only"
            )

    target = set(variables)
    equations: list[sympy.Expr] = []
    for _relation, lhs, rhs in compiled:
        extra = (lhs.free_symbols | rhs.free_symbols) - target
        if extra:
            raise EngineUnsupported(
                "symbolic parameters in a linear system are unsupported"
            )
        residual = sympy.expand(lhs - rhs)
        try:
            polynomial = sympy.Poly(residual, *variables)
        except (sympy.PolynomialError, ValueError, TypeError) as exc:
            raise EngineUnsupported(
                "multi-symbol solving supports linear systems only"
            ) from exc
        if polynomial.total_degree() > 1:
            raise EngineUnsupported("multi-symbol solving supports linear systems only")
        equations.append(residual)

    try:
        solution = sympy.linsolve(equations, variables)
    except (EngineUnknown, EngineUnsupported):
        raise
    except Exception as exc:
        raise EngineUnsupported(
            "the linear system solver could not settle this system"
        ) from exc

    expected_tuple: tuple[sympy.Expr, ...] | None
    if solution is sympy.EmptySet:
        raise EngineUnsupported("the linear system has no unique admissible solution")
    elif isinstance(solution, sympy.ConditionSet):
        raise EngineUnknown("the linear system solver returned a condition set")
    elif isinstance(solution, sympy.FiniteSet):
        if len(solution) != 1:
            raise EngineUnsupported("the linear system has no unique solution")
        candidate_tuple = next(iter(solution))
        if len(candidate_tuple) != len(variables):
            raise EngineUnsupported("the solver returned an unexpected tuple shape")
        if any(value.free_symbols for value in candidate_tuple):
            raise EngineUnsupported("parameterised linear systems are unsupported")
        expected_tuple = tuple(candidate_tuple)
    else:
        raise EngineUnsupported(
            f"unsupported linear system solution shape {type(solution).__name__}"
        )

    conditions: list[_Condition] = []
    for relation in problem.relations:
        conditions.extend(ast_conditions(ctx, relation.lhs))
        conditions.extend(ast_conditions(ctx, relation.rhs))

    if expected_tuple is not None:
        for value, spec in zip(expected_tuple, specs, strict=True):
            state = _membership(value, spec, problem.domain)
            if state is False:
                expected_tuple = None
                break
            if state is None:
                raise EngineUnknown(
                    "linear system solution membership cannot be determined"
                )
    if expected_tuple is not None:
        truth = _conditions_hold(
            conditions, dict(zip(variables, expected_tuple, strict=True))
        )
        if truth is False:
            expected_tuple = None
        elif truth is None:
            raise EngineUnknown(
                "linear system membership in the source domain is undecidable"
            )

    if expected_tuple is None:
        raise EngineUnsupported("the linear system has no unique admissible solution")
    try:
        matches = _check_system_candidate(
            ctx, variables, specs, conditions, expected_tuple
        )
    except _CandidateIncorrect:
        return ctx.result(
            "incorrect",
            "a candidate tuple does not satisfy every original relation",
            "linsolve+domain-check",
            domain=problem.domain,
            relation_count=len(problem.relations),
            expected="EmptySet"
            if expected_tuple is None
            else sympy.sstr(expected_tuple),
        )

    if matches:
        return ctx.result(
            "correct",
            "the ordered tuple is the unique solution of every original relation",
            "linsolve+domain-check",
            domain=problem.domain,
            relation_count=len(problem.relations),
            expected=sympy.sstr(expected_tuple),
        )
    return ctx.result(
        "incorrect",
        "the candidate tuple is not the unique solution of the declared system",
        "linsolve+domain-check",
        domain=problem.domain,
        relation_count=len(problem.relations),
        expected="EmptySet" if expected_tuple is None else sympy.sstr(expected_tuple),
    )


def _conditions_hold(
    conditions: list[_Condition],
    substitutions: dict[sympy.Symbol, sympy.Expr],
) -> bool | None:
    for condition in conditions:
        truth = _evaluate_condition(condition, substitutions)
        if truth is False:
            return False
        if truth is None:
            return None
    return True


def _check_system_candidate(
    ctx: EngineContext,
    variables: list[sympy.Symbol],
    specs: list[SymbolSpec],
    conditions: list[_Condition],
    expected: tuple[sympy.Expr, ...] | None,
) -> bool:
    answer = ctx.request.answer
    if answer.kind != "tuple":
        raise EngineUnsupported(
            "an ordered linear-system answer must use the tuple kind"
        )
    if len(answer.items) != len(variables):
        raise _CandidateIncorrect("the candidate tuple has the wrong length")

    values: list[sympy.Expr] = []
    for item, spec in zip(answer.items, specs, strict=True):
        value = ctx.compile(item)
        _validate_number(value, "a candidate tuple component")
        _validate_membership(value, spec, ctx.request.problem.domain)
        values.append(value)

    substitutions = dict(zip(variables, values, strict=True))
    truth = _conditions_hold(conditions, substitutions)
    if truth is False:
        raise _CandidateIncorrect(
            "a candidate tuple violates an original domain restriction"
        )
    if truth is None:
        raise EngineUnknown("candidate membership in the source domain is undecidable")

    if expected is None:
        return False
    for left, right in zip(values, expected, strict=True):
        exact = _exact_equal(left, right)
        if exact is False:
            return False
        if exact is None:
            raise EngineUnknown(
                "whether two candidate components are equal is undecidable"
            )
    return True


def _exact_equal(left: sympy.Expr, right: sympy.Expr) -> bool | None:
    difference = sympy.simplify(left - right)
    if difference == 0 or difference.is_zero is True:
        return True
    if difference.is_zero is False:
        return False
    expanded = sympy.expand(left - right)
    if expanded == 0 or expanded.is_zero is True:
        return True
    if expanded.is_zero is False:
        return False
    return None
