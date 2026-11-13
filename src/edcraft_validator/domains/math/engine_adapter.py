"""Closed conversion from authored math IR to deterministic-engine requests.

This adapter is the only bridge between an authored :class:`MathItemSpec` (with
an :class:`AnswerRecipe` key or a ``Distractor`` option) and the deterministic
engine. It maps the IR goal vocabulary onto engine operations, binds declared
parameters into concrete expression trees, and refuses with
:class:`AdapterGap` any construct that has no faithful engine operation or
answer kind.

The adapter performs no mathematics and never parses text: it compiles each
expression once with the declared symbols and parameters so an unusable tree
becomes a gap instead of an engine ``error`` outcome, then builds a closed
:class:`CorrectnessRequest` and lets the engine decide. Engine refusals arrive
as honest ``CorrectnessResult`` outcomes (``unknown``/``unsupported``/
``timeout``/``error``); :class:`AdapterGap` is reserved for IR constructs the
engine cannot represent at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

import sympy
from pydantic import ValidationError

from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
    MathAnswer,
    MathProblem,
    Operation,
)
from edcraft_validator.domains.math.engine.dispatch import check_in_process
from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
)
from edcraft_validator.domains.math.ir.instantiate import substitute_expr
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    Expr,
    GoalKind,
    MathItemSpec,
)

_SCALAR_GOAL_OPERATIONS: dict[GoalKind, Operation] = {
    "evaluate": "evaluate",
    "simplify": "simplify",
    "expand": "expand",
    "factor": "factor",
}

# The engine grades matrix operations on exact numeric entries only and refuses
# any declared symbol, while the IR always declares at least one. The adapter
# therefore forwards no symbols for these operations; a matrix cell that still
# references a symbol is refused by the engine instead of silently reinterpreted.
_MATRIX_GOAL_OPERATIONS: dict[GoalKind, Operation] = {
    "determinant": "determinant",
}


class AdapterGap(ValueError):
    """An IR construct has no engine operation or answer kind."""


def to_correctness_request(
    item: MathItemSpec,
    answer: AnswerRecipe | Distractor,
    params: Mapping[str, Fraction] | None = None,
) -> CorrectnessRequest:
    """Build the engine request that grades ``answer`` against ``item``.

    Raises :class:`AdapterGap` when the goal kind has no engine operation, the
    answer kind has no engine answer, or an expression does not compile with
    the declared symbols and parameters.
    """
    symbols = build_symbols(item.symbols)
    try:
        problem = _problem(item, symbols, params)
        engine_answer = _answer(item, answer, symbols, params)
    except ValidationError as exc:
        raise AdapterGap(f"no engine representation for this item: {exc}") from exc
    return CorrectnessRequest(problem=problem, answer=engine_answer)


def grade(
    item: MathItemSpec,
    answer: AnswerRecipe | Distractor,
    params: Mapping[str, Fraction] | None = None,
) -> CorrectnessResult:
    """Grade ``answer`` against ``item`` with the in-process engine.

    Raises :class:`AdapterGap` only for IR the engine cannot represent; every
    other verdict arrives as the returned result's ``outcome``.
    """
    return check_in_process(to_correctness_request(item, answer, params))


# ---------------------------------------------------------------------------
# Problem side


def _problem(
    item: MathItemSpec,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathProblem:
    kind = item.goal.kind
    if kind in _SCALAR_GOAL_OPERATIONS:
        return _scalar_problem(item, symbols, params)
    if kind == "derivative":
        return _calculus_problem(item, symbols, params, "differentiate")
    if kind == "integral":
        return _calculus_problem(item, symbols, params, "antiderivative")
    if kind == "solve":
        return _solve_problem(item, symbols, params)
    if kind in _MATRIX_GOAL_OPERATIONS:
        return _determinant_problem(item, symbols, params)
    raise AdapterGap(f"goal kind {kind!r} has no engine operation")


def _scalar_problem(
    item: MathItemSpec,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathProblem:
    kind = item.goal.kind
    operation = _SCALAR_GOAL_OPERATIONS[kind]
    if item.goal.expr is None:  # unreachable: the IR validator requires it
        raise AdapterGap(f"{kind} goals require an expression")
    _checked(item.goal.expr, symbols, params, f"{kind} goal expression")
    return MathProblem(
        operation=operation,
        symbols=item.symbols,
        expression=_bound(item.goal.expr, params),
    )


def _calculus_problem(
    item: MathItemSpec,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
    operation: Operation,
) -> MathProblem:
    kind = item.goal.kind
    if item.goal.expr is None:  # unreachable: the IR validator requires it
        raise AdapterGap(f"{kind} goals require an expression")
    if item.goal.symbol is None:
        raise AdapterGap(f"{kind} goals require the symbol to operate on")
    _checked(item.goal.expr, symbols, params, f"{kind} goal expression")
    return MathProblem(
        operation=operation,
        symbols=item.symbols,
        expression=_bound(item.goal.expr, params),
        variable=item.goal.symbol,
        order=item.goal.order,
    )


def _solve_problem(
    item: MathItemSpec,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathProblem:
    relations = [
        given.relation
        for given in item.givens
        if given.kind == "relation" and given.relation is not None
    ]
    if not relations:
        raise AdapterGap("solve goals require at least one relation given")
    targets = list(item.goal.symbols)
    if not targets and item.goal.symbol is not None:
        targets = [item.goal.symbol]
    if not targets:  # unreachable: the IR validator requires a target
        raise AdapterGap("solve goals require a symbol or symbols to solve for")
    for index, relation in enumerate(relations):
        _checked(relation.lhs, symbols, params, f"solve relation {index} left side")
        _checked(relation.rhs, symbols, params, f"solve relation {index} right side")
    return MathProblem(
        operation="solve",
        symbols=item.symbols,
        relations=[
            relation.model_copy(
                update={
                    "lhs": _bound(relation.lhs, params),
                    "rhs": _bound(relation.rhs, params),
                }
            )
            for relation in relations
        ],
        solve_for=targets,
        domain=item.goal.domain,
    )


def _determinant_problem(
    item: MathItemSpec,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathProblem:
    matrix = item.goal.matrix
    if not matrix:  # unreachable: the IR validator requires a matrix
        raise AdapterGap("determinant goals require a matrix")
    for row_index, row in enumerate(matrix):
        for column_index, cell in enumerate(row):
            _checked(
                cell,
                symbols,
                params,
                f"determinant matrix [{row_index}][{column_index}]",
            )
    return MathProblem(
        operation=_MATRIX_GOAL_OPERATIONS[item.goal.kind],
        symbols=[],
        matrix=[[_bound(cell, params) for cell in row] for row in matrix],
    )


# ---------------------------------------------------------------------------
# Answer side


def _answer(
    item: MathItemSpec,
    answer: AnswerRecipe | Distractor,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathAnswer:
    if isinstance(answer, Distractor):
        return _distractor_answer(answer, symbols, params)
    return _recipe_answer(answer, symbols, params)


def _recipe_answer(
    recipe: AnswerRecipe,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathAnswer:
    if recipe.kind == "interval":
        raise AdapterGap("interval answers have no engine answer kind")
    if recipe.kind == "boolean":
        raise AdapterGap("boolean answers have no engine answer kind")
    if recipe.kind in {"numeric", "expression"}:
        # The recipe validator guarantees exactly one item for these kinds.
        value = recipe.items[0]
        _checked(value, symbols, params, f"{recipe.kind} answer")
        return MathAnswer(kind="expression", expression=_bound(value, params))
    if recipe.kind in {"set", "tuple"}:
        for index, value in enumerate(recipe.items):
            _checked(value, symbols, params, f"{recipe.kind} answer item {index}")
        return MathAnswer(
            kind=recipe.kind,
            items=[_bound(value, params) for value in recipe.items],
        )
    if recipe.matrix is None:  # unreachable: the recipe validator requires it
        raise AdapterGap("matrix answers require a matrix value")
    for row_index, row in enumerate(recipe.matrix):
        for column_index, cell in enumerate(row):
            _checked(
                cell,
                symbols,
                params,
                f"matrix answer [{row_index}][{column_index}]",
            )
    return MathAnswer(
        kind="matrix",
        matrix=[[_bound(cell, params) for cell in row] for row in recipe.matrix],
    )


def _distractor_answer(
    distractor: Distractor,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
) -> MathAnswer:
    if distractor.value is not None:
        _checked(distractor.value, symbols, params, "distractor value")
        return MathAnswer(
            kind="expression", expression=_bound(distractor.value, params)
        )
    if distractor.items:
        for index, value in enumerate(distractor.items):
            _checked(value, symbols, params, f"distractor item {index}")
        return MathAnswer(
            kind="set", items=[_bound(value, params) for value in distractor.items]
        )
    for index, value in enumerate(distractor.components):
        _checked(value, symbols, params, f"distractor component {index}")
    return MathAnswer(
        kind="tuple",
        items=[_bound(value, params) for value in distractor.components],
    )


# ---------------------------------------------------------------------------
# Shared expression handling


def _checked(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None,
    label: str,
) -> None:
    """Compile once so an unusable expression becomes a gap, not an engine error."""
    try:
        compile_expr(expr, symbols, params)
    except MathCompileError as exc:
        raise AdapterGap(f"{label} does not compile: {exc}") from exc


def _bound(expr: Expr, params: Mapping[str, Fraction] | None) -> Expr:
    """Bind parameter nodes to their declared values for a concrete request."""
    if not params:
        return expr
    return substitute_expr(expr, params)
