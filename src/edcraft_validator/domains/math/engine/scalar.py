"""Deterministic correctness for scalar expression answers.

Supported operations are evaluate/simplify/expand/factor/complete-square,
differentiate, antiderivative and definite-integral.  Expression answers are
compared on the problem's original real domain, not just after SymPy
simplification, so cancelled denominators and branch cuts keep their holes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sympy

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessResult,
    EngineUnknown,
    EngineUnsupported,
    Outcome,
)
from edcraft_validator.domains.math.engine.scalar_domains import (
    Condition,
    Domain,
    ast_conditions,
    compile_ast,
    counterexample,
    domain_covered,
    domain_from_conditions,
    domain_is_empty,
    domain_nonempty,
    intersect_domains,
    merge_conditions,
    provably_zero,
    sympy_domain,
)

_EQUIVALENCE_OPERATIONS = frozenset(
    {"evaluate", "simplify", "expand", "factor", "complete-square"}
)
_CALCULUS_OPERATIONS = frozenset(
    {"differentiate", "antiderivative", "definite-integral"}
)
_SUPPORTED_OPERATIONS = _EQUIVALENCE_OPERATIONS | _CALCULUS_OPERATIONS


@dataclass(frozen=True)
class _Branch:
    source: sympy.Expr
    candidate: sympy.Expr
    source_conditions: tuple[Condition, ...]
    candidate_conditions: tuple[Condition, ...]
    substitution: dict[sympy.Symbol, sympy.Expr] = field(default_factory=dict)


@dataclass(frozen=True)
class _Verdict:
    outcome: Outcome
    reason: str
    method: str
    details: dict[str, object] = field(default_factory=dict)


def check_scalar(ctx: EngineContext) -> CorrectnessResult:
    """Check one scalar expression request against its problem expression."""
    problem = ctx.request.problem
    operation = problem.operation
    if operation not in _SUPPORTED_OPERATIONS:
        raise EngineUnsupported(f"{operation!r} is not a scalar expression operation")

    answer = ctx.request.answer
    if answer.kind != "expression" or answer.expression is None:
        return ctx.result(
            "unsupported",
            "only expression answers are supported",
            "scalar.answer",
        )

    source = compile_ast(ctx, problem.expression)
    candidate = compile_ast(ctx, answer.expression)
    branches = _branches(ctx, source, candidate, operation)
    verdicts = [_run_branch(ctx, operation, branch) for branch in branches]
    return _combine(ctx, operation, verdicts)


def _branches(
    ctx: EngineContext,
    source: sympy.Expr,
    candidate: sympy.Expr,
    operation: str,
) -> list[_Branch]:
    problem = ctx.request.problem
    source_ast = problem.expression
    answer_ast = ctx.request.answer.expression
    assert source_ast is not None and answer_ast is not None
    source_guards = ast_conditions(ctx, source_ast)
    candidate_guards = ast_conditions(ctx, answer_ast)

    equations: list[sympy.Expr] = []
    inequalities: list[Condition] = []
    for relation in problem.relations:
        left = compile_ast(ctx, relation.lhs)
        right = compile_ast(ctx, relation.rhs)
        residual = left - right
        if relation.kind == "eq":
            if provably_zero(residual):
                continue
            equations.append(residual)
        else:
            inequalities.append(Condition(relation.kind, residual))

    if not equations:
        return [
            _Branch(
                source,
                candidate,
                merge_conditions(source_guards + tuple(inequalities)),
                candidate_guards,
            )
        ]

    variable = _problem_variable(ctx)
    if operation in _CALCULUS_OPERATIONS and variable is not None:
        if any(residual.has(variable) for residual in equations):
            raise EngineUnsupported(
                "equations that constrain the calculus variable are unsupported"
            )

    try:
        solutions = sympy.solve(equations, list(ctx.symbols.values()), dict=True)
    except (NotImplementedError, TypeError, ValueError) as exc:
        raise EngineUnknown(f"could not solve the given relations: {exc}") from exc
    if not solutions:
        raise EngineUnsupported("the given equations have no real solutions")

    branches: list[_Branch] = []
    for solution in solutions:
        if not isinstance(solution, dict):
            raise EngineUnknown("the given relations did not produce explicit values")
        substitution = {
            key: value
            for key, value in solution.items()
            if isinstance(key, sympy.Symbol)
        }
        if any(value.is_real is False for value in substitution.values()):
            continue
        try:
            branch_source = source.subs(substitution)
            branch_candidate = candidate.subs(substitution)
        except (TypeError, ValueError) as exc:
            raise EngineUnknown(f"could not apply the given relations: {exc}") from exc
        source_conditions = tuple(
            guard.substitute(substitution) for guard in source_guards
        ) + tuple(condition.substitute(substitution) for condition in inequalities)
        candidate_conditions = tuple(
            guard.substitute(substitution) for guard in candidate_guards
        )
        branches.append(
            _Branch(
                branch_source,
                branch_candidate,
                merge_conditions(source_conditions),
                merge_conditions(candidate_conditions),
                substitution,
            )
        )
    if not branches:
        raise EngineUnsupported("the given equations have no real solutions")
    return branches


def _run_branch(
    ctx: EngineContext,
    operation: str,
    branch: _Branch,
) -> _Verdict | None:
    if operation in _EQUIVALENCE_OPERATIONS:
        return _check_equivalence(ctx, branch)
    if operation == "differentiate":
        return _check_differentiate(ctx, branch)
    if operation == "antiderivative":
        return _check_antiderivative(ctx, branch)
    if operation == "definite-integral":
        return _check_definite_integral(ctx, branch)
    raise EngineUnsupported(f"{operation!r} is not a scalar expression operation")


def _check_equivalence(ctx: EngineContext, branch: _Branch) -> _Verdict | None:
    variable = _variable_for(ctx, branch)
    source_domain = domain_from_conditions(
        ctx, branch.source, branch.source_conditions, variable
    )
    candidate_domain = domain_from_conditions(
        ctx, branch.candidate, branch.candidate_conditions, variable
    )
    nonempty = domain_nonempty(ctx, source_domain)
    if nonempty is False:
        return None
    if nonempty is None:
        return _Verdict(
            "unknown",
            "could not establish that the problem's real domain is non-empty",
            "scalar.equivalence.domain",
        )
    coverage = domain_covered(source_domain, candidate_domain, ctx)
    if coverage is False:
        return _Verdict(
            "incorrect",
            "the answer is not defined on the problem's whole real domain",
            "scalar.equivalence.domain",
        )
    if coverage is None:
        return _Verdict(
            "unknown",
            "could not establish the answer's domain on the problem domain",
            "scalar.equivalence.domain",
        )
    return _compare_expressions(
        ctx,
        branch.source,
        branch.candidate,
        source_domain,
        "scalar.equivalence",
        "expressions are exactly equivalent on the problem's real domain",
        "expressions differ at a valid exact point",
    )


def _check_differentiate(ctx: EngineContext, branch: _Branch) -> _Verdict | None:
    variable = _problem_variable(ctx)
    if variable is None:
        raise EngineUnsupported("differentiation requires a declared variable")
    source_domain = domain_from_conditions(
        ctx, branch.source, branch.source_conditions, variable
    )
    nonempty = domain_nonempty(ctx, source_domain)
    if nonempty is False:
        return None
    if nonempty is None:
        return _Verdict(
            "unknown",
            "could not establish that the problem's real domain is non-empty",
            "scalar.differentiate.domain",
        )
    try:
        expected = sympy.diff(branch.source, variable, ctx.request.problem.order)
    except (TypeError, ValueError) as exc:
        raise EngineUnsupported(f"could not differentiate expression: {exc}") from exc
    if expected.has(sympy.Derivative, sympy.Integral):
        raise EngineUnsupported("the derivative is not an explicit expression")
    if expected.has(sympy.nan, sympy.zoo, sympy.oo, -sympy.oo):
        raise EngineUnsupported("the derivative is not finite on its domain")
    expected_domain = sympy_domain(ctx, expected, variable)
    required_domain = intersect_domains(source_domain, expected_domain)
    required_empty = domain_is_empty(required_domain)
    if required_empty is True:
        raise EngineUnsupported("the derivative has no real differentiability domain")
    if required_empty is None:
        return _Verdict(
            "unknown",
            "could not determine the derivative's real domain",
            "scalar.differentiate.domain",
        )
    candidate_domain = domain_from_conditions(
        ctx, branch.candidate, branch.candidate_conditions, variable
    )
    coverage = domain_covered(required_domain, candidate_domain, ctx)
    if coverage is False:
        return _Verdict(
            "incorrect",
            "the derivative answer is not defined on the differentiability domain",
            "scalar.differentiate.domain",
        )
    if coverage is None:
        return _Verdict(
            "unknown",
            "could not establish the derivative answer's domain",
            "scalar.differentiate.domain",
        )
    return _compare_expressions(
        ctx,
        expected,
        branch.candidate,
        required_domain,
        "scalar.differentiate",
        "the answer is the exact derivative on the source domain",
        "the answer differs from the derivative at a valid exact point",
    )


def _check_antiderivative(ctx: EngineContext, branch: _Branch) -> _Verdict | None:
    variable = _problem_variable(ctx)
    if variable is None:
        raise EngineUnsupported("antidifferentiation requires a declared variable")
    source_domain = domain_from_conditions(
        ctx, branch.source, branch.source_conditions, variable
    )
    nonempty = domain_nonempty(ctx, source_domain)
    if nonempty is False:
        return None
    if nonempty is None:
        return _Verdict(
            "unknown",
            "could not establish that the integrand's real domain is non-empty",
            "scalar.antiderivative.domain",
        )
    candidate_domain = domain_from_conditions(
        ctx, branch.candidate, branch.candidate_conditions, variable
    )
    coverage = domain_covered(source_domain, candidate_domain, ctx)
    if coverage is False:
        return _Verdict(
            "incorrect",
            "the primitive is not defined on the integrand's whole real domain",
            "scalar.antiderivative.domain",
        )
    if coverage is None:
        return _Verdict(
            "unknown",
            "could not establish the primitive's domain on the integrand domain",
            "scalar.antiderivative.domain",
        )
    try:
        derivative = sympy.diff(branch.candidate, variable)
    except (TypeError, ValueError) as exc:
        raise EngineUnsupported(f"could not differentiate the answer: {exc}") from exc
    if derivative.has(
        sympy.Derivative,
        sympy.Integral,
        sympy.nan,
        sympy.zoo,
        sympy.oo,
        -sympy.oo,
    ):
        raise EngineUnsupported("the answer's derivative is not an explicit expression")
    derivative_domain = sympy_domain(ctx, derivative, variable)
    differentiable = domain_covered(source_domain, derivative_domain, ctx)
    if differentiable is False:
        return _Verdict(
            "incorrect",
            "the primitive is not differentiable on the integrand's whole domain",
            "scalar.antiderivative.domain",
        )
    if differentiable is None:
        return _Verdict(
            "unknown",
            "could not establish the primitive's differentiability domain",
            "scalar.antiderivative.domain",
        )
    return _compare_expressions(
        ctx,
        derivative,
        branch.source,
        source_domain,
        "scalar.antiderivative",
        "the answer differentiates exactly to the integrand on its domain",
        "the answer's derivative differs from the integrand at a valid exact point",
    )


def _check_definite_integral(ctx: EngineContext, branch: _Branch) -> _Verdict | None:
    problem = ctx.request.problem
    variable = _problem_variable(ctx)
    if variable is None:
        raise EngineUnsupported("definite integration requires a declared variable")
    lower = compile_ast(ctx, problem.lower).subs(branch.substitution)
    upper = compile_ast(ctx, problem.upper).subs(branch.substitution)
    if not _finite_real_constant(lower) or not _finite_real_constant(upper):
        return _Verdict(
            "unsupported",
            "definite integral endpoints must be finite real constants",
            "scalar.definite-integral.endpoints",
        )

    source_domain = domain_from_conditions(
        ctx, branch.source, branch.source_conditions, variable
    )
    nonempty = domain_nonempty(ctx, source_domain)
    if nonempty is False:
        return None
    if nonempty is None:
        return _Verdict(
            "unknown",
            "could not establish that the integrand's real domain is non-empty",
            "scalar.definite-integral.domain",
        )
    if source_domain.point_set is None:
        return _Verdict(
            "unknown",
            "could not determine the integrand's real domain on the interval",
            "scalar.definite-integral.domain",
        )
    low, high = sorted((lower, upper))
    if sympy.Interval(low, high).is_subset(source_domain.point_set) is not True:
        return _Verdict(
            "unknown",
            "definite integral touches a non-removable singularity or improper point",
            "scalar.definite-integral.domain",
        )

    candidate_domain = domain_from_conditions(
        ctx, branch.candidate, branch.candidate_conditions, variable
    )
    coverage = domain_covered(source_domain, candidate_domain, ctx)
    if coverage is False:
        return _Verdict(
            "incorrect",
            "the integral answer is not defined on the integrand's whole domain",
            "scalar.definite-integral.domain",
        )
    if coverage is None:
        return _Verdict(
            "unknown",
            "could not establish the integral answer's domain",
            "scalar.definite-integral.domain",
        )

    try:
        expected = sympy.integrate(branch.source, (variable, lower, upper))
        expected = sympy.simplify(expected)
    except (NotImplementedError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise EngineUnknown(f"could not evaluate the definite integral: {exc}") from exc
    if expected.has(sympy.Integral, sympy.Derivative):
        raise EngineUnsupported("the definite integral is not an explicit expression")
    if expected.has(sympy.Piecewise):
        return _Verdict(
            "unknown",
            "the definite integral is conditional on branch assumptions",
            "scalar.definite-integral",
        )
    if expected.has(sympy.nan, sympy.zoo, sympy.oo, -sympy.oo):
        return _Verdict(
            "unknown",
            "the definite integral is divergent or otherwise non-finite",
            "scalar.definite-integral",
        )
    if expected.is_finite is False:
        return _Verdict(
            "unknown",
            "the definite integral is not finite",
            "scalar.definite-integral",
        )
    return _compare_expressions(
        ctx,
        expected,
        branch.candidate,
        source_domain,
        "scalar.definite-integral",
        "the answer equals the exact definite integral",
        "the answer differs from the definite integral at a valid exact point",
    )


def _compare_expressions(
    ctx: EngineContext,
    expected: sympy.Expr,
    candidate: sympy.Expr,
    domain: Domain,
    method: str,
    correct_reason: str,
    incorrect_reason: str,
) -> _Verdict:
    difference = expected - candidate
    if provably_zero(difference, domain):
        return _Verdict("correct", correct_reason, method)
    witness = counterexample(
        difference, domain, ctx, extra_symbols=difference.free_symbols
    )
    if witness is not None:
        return _Verdict(
            "incorrect",
            incorrect_reason,
            method,
            {"witness": {name: sympy.sstr(value) for name, value in witness.items()}},
        )
    return _Verdict(
        "unknown",
        "could not prove exact equality and found no exact counterexample",
        method,
    )


def _combine(
    ctx: EngineContext,
    operation: str,
    verdicts: list[_Verdict | None],
) -> CorrectnessResult:
    actual = [verdict for verdict in verdicts if verdict is not None]
    if not actual:
        return ctx.result(
            "unsupported",
            "the given relations leave no real inputs for this problem",
            f"scalar.{operation}",
        )
    for outcome in ("incorrect", "unknown", "unsupported"):
        for verdict in actual:
            if verdict.outcome == outcome:
                return ctx.result(
                    verdict.outcome,
                    verdict.reason,
                    verdict.method,
                    branch_count=len(actual),
                    **verdict.details,
                )
    first = actual[0]
    return ctx.result(
        first.outcome,
        first.reason,
        first.method,
        branch_count=len(actual),
        **first.details,
    )


def _problem_variable(ctx: EngineContext) -> sympy.Symbol | None:
    name = ctx.request.problem.variable
    if name is None:
        return None
    return ctx.symbols.get(name)


def _variable_for(ctx: EngineContext, branch: _Branch) -> sympy.Symbol | None:
    variable = _problem_variable(ctx)
    if variable is not None:
        return variable
    symbols = set(branch.source.free_symbols) | set(branch.candidate.free_symbols)
    if len(symbols) == 1:
        return next(iter(symbols))
    return None


def _finite_real_constant(value: sympy.Expr) -> bool:
    return value.is_number and value.is_real is True and value.is_finite is True
