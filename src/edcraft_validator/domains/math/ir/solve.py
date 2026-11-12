"""Deterministically solve a concrete math IR with exact SymPy arithmetic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

import sympy
from sympy.matrices.matrixbase import MatrixBase

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
    compile_givens,
    compile_relation,
)
from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Given,
    Goal,
    Interval,
    MathItemSpec,
    Relation,
)

_DOMAINS = {
    "real": sympy.S.Reals,
    "integer": sympy.S.Integers,
    "rational": sympy.S.Rationals,
}


class SolveUnavailable(MathCompileError):
    """The symbolic solver could not decide the goal."""


@dataclass(frozen=True)
class SolveResult:
    value: object
    answer: Answer
    display: str


def goal_symbols(goal: Goal) -> tuple[str, ...]:
    if goal.symbols:
        return tuple(goal.symbols)
    if goal.symbol is not None:
        return (goal.symbol,)
    return ()


def solve_item(
    spec: MathItemSpec, params: Mapping[str, Fraction] | None = None
) -> SolveResult:
    symbols = build_symbols(spec.symbols)
    return solve_goal(spec.goal, spec.givens, symbols, params)


def solve_goal(
    goal: Goal,
    givens: list[Given],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> SolveResult:
    values = params or {}
    if goal.kind == "solve":
        relations = compile_givens(givens, symbols, values)
        if not relations:
            raise SolveUnavailable("solve goals require at least one relation")
        names = goal_symbols(goal)
        if len(names) == 1:
            solution = _solve_single(relations[0], symbols[names[0]], goal.domain)
        else:
            solution = _solve_system(relations, [symbols[name] for name in names])
        return SolveResult(solution, answer_from_sympy(solution), sympy.sstr(solution))

    if goal.kind in {"determinant", "eigenvalues"}:
        matrix = sympy.Matrix(_matrix(goal, symbols, values))
        if goal.kind == "determinant":
            value = matrix.det()
        else:
            value = sympy.FiniteSet(*matrix.eigenvals().keys())
        if value is sympy.nan or value is sympy.zoo:
            raise SolveUnavailable("goal evaluated to an undefined value")
        return SolveResult(value, answer_from_sympy(value), sympy.sstr(value))

    expression = _goal_expression(goal, symbols, values)
    if goal.kind == "evaluate":
        value = sympy.simplify(expression)
    elif goal.kind == "simplify":
        value = sympy.simplify(expression)
    elif goal.kind == "factor":
        value = sympy.factor(expression)
    elif goal.kind == "expand":
        value = sympy.expand(expression)
    elif goal.kind == "derivative":
        if goal.symbol is None:
            raise SolveUnavailable("derivative goals require a symbol")
        value = sympy.diff(expression, symbols[goal.symbol], goal.order)
    elif goal.kind == "integral":
        if goal.symbol is None:
            raise SolveUnavailable("integral goals require a symbol")
        value = sympy.integrate(expression, symbols[goal.symbol])
    elif goal.kind == "limit":
        if goal.symbol is None or goal.point is None:
            raise SolveUnavailable("limit goals require a symbol and point")
        point = compile_expr(goal.point, symbols, values)
        value = sympy.limit(expression, symbols[goal.symbol], point)
    else:  # pragma: no cover - the schema literal is exhaustive
        raise SolveUnavailable(f"unsupported goal kind {goal.kind!r}")
    if value is sympy.nan or value is sympy.zoo:
        raise SolveUnavailable("goal evaluated to an undefined value")
    return SolveResult(value, answer_from_sympy(value), sympy.sstr(value))


def _goal_expression(
    goal: Goal,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> sympy.Expr:
    if goal.expr is None:
        raise SolveUnavailable(f"{goal.kind} goals require an expression")
    return compile_expr(goal.expr, symbols, params)


def _matrix(
    goal: Goal,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> list[list[sympy.Expr]]:
    if goal.matrix is None:
        raise SolveUnavailable(f"{goal.kind} goals require a matrix")
    return [
        [compile_expr(cell, symbols, params) for cell in row] for row in goal.matrix
    ]


def _solve_single(relation: sympy.Rel, symbol: sympy.Symbol, domain: str) -> sympy.Set:
    solution = sympy.solveset(relation, symbol, domain=_DOMAINS[domain])
    if isinstance(solution, sympy.ConditionSet):
        raise SolveUnavailable("the solver returned a conditional solution set")
    if isinstance(solution, sympy.FiniteSet):
        admitted = _admit_roots(relation, symbol, list(solution))
        return sympy.FiniteSet(*admitted)
    return solution


def _solve_system(relations: list[sympy.Rel], symbols: list[sympy.Symbol]) -> sympy.Set:
    try:
        result = sympy.linsolve(relations, symbols)
    except Exception:
        result = sympy.nonlinsolve(relations, symbols)
    if isinstance(result, sympy.ConditionSet):
        raise SolveUnavailable("the system solver returned a conditional set")
    if not isinstance(result, sympy.FiniteSet):
        return result
    admitted = []
    for candidate in result:
        values = (
            candidate if isinstance(candidate, (tuple, sympy.Tuple)) else (candidate,)
        )
        if len(values) != len(symbols):
            continue
        if not all(value.is_real for value in values):
            continue
        if all(
            sympy.simplify(relation.subs(dict(zip(symbols, values, strict=True))))
            is sympy.true
            for relation in relations
        ):
            admitted.append(candidate)
    return sympy.FiniteSet(*admitted)


def _admit_roots(
    relation: sympy.Rel, symbol: sympy.Symbol, candidates: list[sympy.Expr]
) -> list[sympy.Expr]:
    residual = relation.lhs - relation.rhs
    denominator = sympy.denom(sympy.together(residual))
    admitted = []
    for candidate in candidates:
        if not candidate.is_real or candidate.has(sympy.zoo, sympy.nan, sympy.oo):
            continue
        try:
            if sympy.simplify(denominator.subs(symbol, candidate)) == 0:
                continue
            if sympy.simplify(residual.subs(symbol, candidate)) != 0:
                continue
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        admitted.append(candidate)
    return admitted


def answer_from_sympy(value: object) -> Answer:
    if isinstance(value, sympy.FiniteSet):
        items = sorted(value.args, key=sympy.default_sort_key)
        if len(items) == 1 and items[0].is_number:
            text = sympy.sstr(items[0])
            return Answer(kind="numeric", items=[text], display=text)
        if len(items) == 1 and isinstance(items[0], sympy.Tuple):
            return Answer(
                kind="tuple",
                items=[sympy.sstr(item) for item in items[0]],
                display=sympy.sstr(items[0]),
            )
        rendered = [sympy.sstr(item) for item in items]
        return Answer(
            kind="set",
            items=rendered,
            display="{" + ", ".join(rendered) + "}",
        )
    if isinstance(value, sympy.Interval):
        return Answer(
            kind="interval",
            items=[sympy.sstr(value)],
            interval=Interval(
                lower=(
                    None
                    if value.start is sympy.S.NegativeInfinity
                    else sympy.sstr(value.start)
                ),
                upper=(
                    None if value.end is sympy.S.Infinity else sympy.sstr(value.end)
                ),
                lower_open=bool(value.left_open),
                upper_open=bool(value.right_open),
            ),
            display=sympy.sstr(value),
        )
    if isinstance(value, sympy.Tuple):
        return Answer(
            kind="tuple",
            items=[sympy.sstr(item) for item in value],
            display=sympy.sstr(value),
        )
    if isinstance(value, MatrixBase):
        return Answer(
            kind="matrix",
            matrix=[[sympy.sstr(cell) for cell in row] for row in value.tolist()],
            display=sympy.sstr(value),
        )
    if value is sympy.EmptySet:
        return Answer(kind="set", items=[], display="{}")
    if value is sympy.S.Reals:
        return Answer(kind="interval", items=["(-oo, oo)"], display="(-oo, oo)")
    if value is sympy.true or value is sympy.false:
        return Answer(kind="boolean", boolean=bool(value), display=str(bool(value)))
    if isinstance(value, sympy.Expr):
        text = sympy.sstr(value)
        if value.is_number:
            return Answer(kind="numeric", items=[text], display=text)
        return Answer(kind="expression", items=[text], display=text)
    raise SolveUnavailable(f"unsupported answer value {type(value).__name__}")


def relation_for(relation: Relation, symbols: Mapping[str, sympy.Symbol]) -> sympy.Rel:
    return compile_relation(relation, symbols)
