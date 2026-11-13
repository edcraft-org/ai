"""Exact correctness checks for matrix-operation answers.

Only exact numeric matrix entries are accepted here.  The shared request
validator already rejects symbolic matrix problems; this module re-checks the
raw expression tree so a direct handler call cannot let cancellation erase a
domain hole.  Candidate cells are compared by exact residual transformations,
never by floating-point tolerance or by treating an unknown ``is_zero`` as
false.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import sympy

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessResult,
    EngineUnknown,
    EngineUnsupported,
)
from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.schema import Expr

_State = Literal["equal", "unequal", "unknown"]
_Matrix = list[list[sympy.Expr]]
_MAX_RESIDUAL_TEXT = 200

_ZERO_TRANSFORMS = (
    sympy.cancel,
    sympy.together,
    sympy.expand,
    sympy.factor,
    sympy.radsimp,
    sympy.trigsimp,
    sympy.simplify,
)


@dataclass(frozen=True)
class _Evidence:
    state: _State
    cells_checked: int = 0
    nonzero_cells: int = 0
    unresolved_cells: int = 0
    first_cell: tuple[int, int] | None = None
    first_residual: sympy.Expr | None = None


def check_matrices(ctx: EngineContext) -> CorrectnessResult:
    """Check one matrix-multiply, determinant, inverse or LU answer."""
    operation = ctx.request.problem.operation
    if operation == "matrix-multiply":
        return _check_multiply(ctx)
    if operation == "determinant":
        return _check_determinant(ctx)
    if operation == "inverse":
        return _check_inverse(ctx)
    if operation == "lu":
        return _check_lu(ctx)
    raise EngineUnsupported(f"unsupported matrix operation {operation!r}")


def _check_multiply(ctx: EngineContext) -> CorrectnessResult:
    problem = ctx.request.problem
    method = "matrix.multiply.exact"
    left = _compile_problem_matrix(ctx, problem.matrix, "problem.matrix")
    right = _compile_problem_matrix(ctx, problem.right_matrix, "problem.right_matrix")
    if len(left[0]) != len(right):
        raise EngineUnsupported(
            "matrix multiplication requires matching inner dimensions"
        )
    expected = _matmul(left, right)
    expected_shape = (len(left), len(right[0]))

    answer = ctx.request.answer
    if answer.kind != "matrix" or answer.matrix is None:
        return _wrong_answer_kind(
            ctx,
            operation="matrix-multiply",
            method=method,
            expected="matrix",
            actual=answer.kind,
        )
    if not _has_shape(answer.matrix, *expected_shape):
        return _wrong_shape(
            ctx,
            operation="matrix-multiply",
            method=method,
            expected=expected_shape,
            dimensions=_dimensions(answer.matrix),
        )
    if _matrix_has_symbols(answer.matrix):
        return _symbolic_candidate(ctx, operation="matrix-multiply", method=method)

    candidate = _compile_candidate_matrix(ctx, answer.matrix, "candidate matrix")
    if not _candidate_entries_are_finite_real(candidate):
        return ctx.result(
            "incorrect",
            "candidate matrix contains a non-finite or non-real entry",
            method,
            operation="matrix-multiply",
            candidate_dimensions=_dimensions(answer.matrix),
        )

    evidence = _matrix_evidence(candidate, expected)
    return _finish(
        ctx,
        operation="matrix-multiply",
        method=method,
        evidence=evidence,
        correct_reason="candidate matrix is the exact product",
        incorrect_reason="candidate matrix differs from the exact product",
        unknown_reason="product residuals could not be resolved exactly",
        extra={
            "left_dimensions": [len(left), len(left[0])],
            "right_dimensions": [len(right), len(right[0])],
        },
    )


def _check_determinant(ctx: EngineContext) -> CorrectnessResult:
    method = "matrix.determinant.exact"
    matrix = _square_problem(ctx, operation="determinant")
    expected = sympy.Matrix(matrix).det()

    answer = ctx.request.answer
    if answer.kind != "expression" or answer.expression is None:
        return _wrong_answer_kind(
            ctx,
            operation="determinant",
            method=method,
            expected="expression",
            actual=answer.kind,
        )
    if _has_raw_symbol(answer.expression):
        return _symbolic_candidate(ctx, operation="determinant", method=method)

    candidate = _compile_candidate_expr(ctx, answer.expression, "candidate expression")
    if _definitely_not_finite_real(candidate):
        return ctx.result(
            "incorrect",
            "candidate determinant is not a finite real value",
            method,
            operation="determinant",
        )

    evidence = _scalar_evidence(candidate, expected)
    return _finish(
        ctx,
        operation="determinant",
        method=method,
        evidence=evidence,
        correct_reason="candidate expression is exactly equal to the determinant",
        incorrect_reason="candidate expression differs from the determinant",
        unknown_reason="the determinant residual could not be resolved exactly",
        extra={"problem_dimensions": [len(matrix), len(matrix[0])]},
    )


def _check_inverse(ctx: EngineContext) -> CorrectnessResult:
    method = "matrix.inverse.two-sided"
    matrix = _square_problem(ctx, operation="inverse")
    size = len(matrix)
    determinant = sympy.Matrix(matrix).det()
    determinant_state = _zero_state(determinant)
    if determinant_state == "equal":
        raise EngineUnsupported("inverse is undefined for a singular matrix")
    if determinant_state == "unknown":
        raise EngineUnknown("could not determine whether the matrix is nonsingular")

    answer = ctx.request.answer
    if answer.kind != "matrix" or answer.matrix is None:
        return _wrong_answer_kind(
            ctx,
            operation="inverse",
            method=method,
            expected="matrix",
            actual=answer.kind,
        )
    if not _has_shape(answer.matrix, size, size):
        return _wrong_shape(
            ctx,
            operation="inverse",
            method=method,
            expected=(size, size),
            dimensions=_dimensions(answer.matrix),
        )
    if _matrix_has_symbols(answer.matrix):
        return _symbolic_candidate(ctx, operation="inverse", method=method)

    candidate = _compile_candidate_matrix(ctx, answer.matrix, "candidate inverse")
    if not _candidate_entries_are_finite_real(candidate):
        return ctx.result(
            "incorrect",
            "candidate inverse contains a non-finite or non-real entry",
            method,
            operation="inverse",
            candidate_dimensions=_dimensions(answer.matrix),
        )

    identity = _identity(size)
    left = _matrix_evidence(_matmul(matrix, candidate), identity)
    right = _matrix_evidence(_matmul(candidate, matrix), identity)
    evidence = _merge(left, right)
    return _finish(
        ctx,
        operation="inverse",
        method=method,
        evidence=evidence,
        correct_reason="candidate matrix satisfies both exact inverse products",
        incorrect_reason="candidate matrix fails an exact inverse product",
        unknown_reason="inverse product residuals could not be resolved exactly",
        extra={"problem_dimensions": [size, size]},
    )


def _check_lu(ctx: EngineContext) -> CorrectnessResult:
    method = "matrix.lu.definition"
    matrix = _square_problem(ctx, operation="lu")
    size = len(matrix)

    answer = ctx.request.answer
    if answer.kind != "lu":
        return _wrong_answer_kind(
            ctx, operation="lu", method=method, expected="lu", actual=answer.kind
        )
    if answer.permutation is None or answer.lower is None or answer.upper is None:
        return ctx.result(
            "incorrect",
            "candidate LU answer is incomplete",
            method,
            operation="lu",
        )
    matrices = {
        "permutation": answer.permutation,
        "lower": answer.lower,
        "upper": answer.upper,
    }
    if any(not _has_shape(value, size, size) for value in matrices.values()):
        return _wrong_shape(
            ctx,
            operation="lu",
            method=method,
            expected=(size, size),
            dimensions=[_dimensions(value) for value in matrices.values()],
            label="candidate permutation, lower and upper matrices",
        )
    if any(_matrix_has_symbols(value) for value in matrices.values()):
        return _symbolic_candidate(ctx, operation="lu", method=method)

    permutation = _compile_candidate_matrix(
        ctx, answer.permutation, "candidate permutation"
    )
    lower = _compile_candidate_matrix(ctx, answer.lower, "candidate lower matrix")
    upper = _compile_candidate_matrix(ctx, answer.upper, "candidate upper matrix")
    if not all(
        _candidate_entries_are_finite_real(value)
        for value in (permutation, lower, upper)
    ):
        return ctx.result(
            "incorrect",
            "candidate LU matrices contain a non-finite or non-real entry",
            method,
            operation="lu",
        )

    permutation_state = _permutation_state(permutation)
    lower_state = _unit_lower_state(lower)
    upper_state = _upper_triangular_state(upper)
    structural = _merge(
        _state_evidence(permutation_state),
        _state_evidence(lower_state),
        _state_evidence(upper_state),
    )
    product = _matrix_evidence(
        _matmul(permutation, matrix),
        _matmul(lower, upper),
    )
    evidence = _merge(structural, product)
    return _finish(
        ctx,
        operation="lu",
        method=method,
        evidence=evidence,
        correct_reason="candidate P, L and U satisfy the exact LU definition",
        incorrect_reason="candidate P, L or U violates the exact LU definition",
        unknown_reason="LU structural or product residuals could not be resolved",
        extra={
            "permutation": _state_label(permutation_state),
            "lower": _state_label(lower_state),
            "upper": _state_label(upper_state),
            "problem_dimensions": [size, size],
        },
    )


def _square_problem(ctx: EngineContext, *, operation: str) -> _Matrix:
    matrix = _compile_problem_matrix(ctx, ctx.request.problem.matrix, "problem.matrix")
    if len(matrix) != len(matrix[0]):
        raise EngineUnsupported(f"{operation} requires a square matrix")
    return matrix


def _compile_problem_matrix(
    ctx: EngineContext,
    matrix: list[list[Expr]] | None,
    label: str,
) -> _Matrix:
    if matrix is None:
        raise EngineUnsupported(f"{label} is required")
    if not matrix or not matrix[0]:
        raise EngineUnsupported(f"{label} must be nonempty")
    columns = len(matrix[0])
    if any(len(row) != columns for row in matrix):
        raise EngineUnsupported(f"{label} must be rectangular")

    # Reject raw symbol references before compilation can cancel a hole.
    for row_index, row in enumerate(matrix):
        for column_index, cell in enumerate(row):
            _require_raw_numeric(cell, f"{label}[{row_index}][{column_index}]")

    compiled = _compile_rows(ctx, matrix, label)
    for row_index, row in enumerate(compiled):
        for column_index, value in enumerate(row):
            _require_exact_real_finite(value, f"{label}[{row_index}][{column_index}]")
    return compiled


def _compile_candidate_matrix(
    ctx: EngineContext, matrix: list[list[Expr]], label: str
) -> _Matrix:
    return _compile_rows(ctx, matrix, label)


def _compile_candidate_expr(
    ctx: EngineContext, expression: Expr, label: str
) -> sympy.Expr:
    try:
        return ctx.compile(expression)
    except MathCompileError as exc:
        raise EngineUnsupported(
            f"{label} is outside the supported exact expression subset: {exc}"
        ) from exc


def _compile_rows(ctx: EngineContext, matrix: list[list[Expr]], label: str) -> _Matrix:
    compiled: _Matrix = []
    for row_index, row in enumerate(matrix):
        compiled_row: list[sympy.Expr] = []
        for column_index, cell in enumerate(row):
            try:
                compiled_row.append(ctx.compile(cell))
            except MathCompileError as exc:
                raise EngineUnsupported(
                    f"{label}[{row_index}][{column_index}] is outside the "
                    f"supported exact expression subset: {exc}"
                ) from exc
        compiled.append(compiled_row)
    return compiled


def _require_raw_numeric(expression: Expr, label: str) -> None:
    pending = [expression]
    while pending:
        node = pending.pop()
        if node.sym is not None or node.param is not None:
            raise EngineUnsupported(f"{label} must contain only exact numeric entries")
        pending.extend(node.args)


def _has_raw_symbol(expression: Expr) -> bool:
    pending = [expression]
    while pending:
        node = pending.pop()
        if node.sym is not None or node.param is not None:
            return True
        pending.extend(node.args)
    return False


def _matrix_has_symbols(matrix: list[list[Expr]]) -> bool:
    return any(_has_raw_symbol(cell) for row in matrix for cell in row)


def _symbolic_candidate(
    ctx: EngineContext, *, operation: str, method: str
) -> CorrectnessResult:
    return ctx.result(
        "unknown",
        "candidate answer contains symbolic entries that cannot be verified "
        "for a numeric matrix problem",
        method,
        operation=operation,
        unresolved_cells=1,
    )


def _require_exact_real_finite(value: sympy.Expr, label: str) -> None:
    if value is sympy.nan or value.has(sympy.Float):
        raise EngineUnsupported(f"{label} must be an exact finite real number")
    if value.free_symbols or not value.is_number:
        raise EngineUnsupported(f"{label} must be an exact numeric expression")
    if value.is_real is not True or value.is_finite is not True:
        raise EngineUnsupported(f"{label} must be a finite real number")


def _candidate_entries_are_finite_real(matrix: _Matrix) -> bool:
    return all(
        not _definitely_not_finite_real(value) for row in matrix for value in row
    )


def _definitely_not_finite_real(value: sympy.Expr) -> bool:
    return value is sympy.nan or value.is_real is False or value.is_finite is False


def _matrix_evidence(actual: _Matrix, expected: _Matrix) -> _Evidence:
    checks: list[_Evidence] = []
    for row_index, (actual_row, expected_row) in enumerate(
        zip(actual, expected, strict=True)
    ):
        if len(actual_row) != len(expected_row):
            return _Evidence("unequal", nonzero_cells=1)
        for column_index, (actual_cell, expected_cell) in enumerate(
            zip(actual_row, expected_row, strict=True)
        ):
            checks.append(
                _cell_evidence(actual_cell, expected_cell, (row_index, column_index))
            )
    return _merge(*checks)


def _scalar_evidence(actual: sympy.Expr, expected: sympy.Expr) -> _Evidence:
    residual = actual - expected
    state = _residual_state(residual)
    if state == "equal":
        return _Evidence("equal", cells_checked=1)
    return _Evidence(
        state,
        cells_checked=1,
        nonzero_cells=1 if state == "unequal" else 0,
        unresolved_cells=1 if state == "unknown" else 0,
        first_residual=residual,
    )


def _cell_evidence(
    actual: sympy.Expr,
    expected: sympy.Expr,
    cell: tuple[int, int],
) -> _Evidence:
    residual = actual - expected
    state = _residual_state(residual)
    if state == "equal":
        return _Evidence("equal", cells_checked=1)
    return _Evidence(
        state,
        cells_checked=1,
        nonzero_cells=1 if state == "unequal" else 0,
        unresolved_cells=1 if state == "unknown" else 0,
        first_cell=cell,
        first_residual=residual,
    )


def _state_evidence(state: _State) -> _Evidence:
    return _Evidence(
        state,
        cells_checked=1,
        nonzero_cells=1 if state == "unequal" else 0,
        unresolved_cells=1 if state == "unknown" else 0,
    )


def _merge(*items: _Evidence) -> _Evidence:
    state: _State = "equal"
    cells_checked = 0
    nonzero_cells = 0
    unresolved_cells = 0
    first_cell: tuple[int, int] | None = None
    first_residual: sympy.Expr | None = None
    for item in items:
        cells_checked += item.cells_checked
        nonzero_cells += item.nonzero_cells
        unresolved_cells += item.unresolved_cells
        state = _worse(state, item.state)
        if first_cell is None and item.first_cell is not None:
            first_cell = item.first_cell
            first_residual = item.first_residual
    return _Evidence(
        state,
        cells_checked=cells_checked,
        nonzero_cells=nonzero_cells,
        unresolved_cells=unresolved_cells,
        first_cell=first_cell,
        first_residual=first_residual,
    )


def _residual_state(residual: sympy.Expr) -> _State:
    state = _zero_state(residual)
    if state != "unknown":
        return state
    for transform in _ZERO_TRANSFORMS:
        try:
            transformed = transform(residual)
        except Exception:  # optional simplifiers raise domain-specific errors
            continue
        state = _zero_state(transformed)
        if state != "unknown":
            return state
    return "unknown"


def _zero_state(value: sympy.Expr) -> _State:
    if value == 0:
        return "equal"
    is_zero = value.is_zero
    if is_zero is True:
        return "equal"
    if is_zero is False:
        return "unequal"
    return "unknown"


def _matmul(left: _Matrix, right: _Matrix) -> _Matrix:
    product = sympy.Matrix(left) * sympy.Matrix(right)
    return [
        [product[row, column] for column in range(product.cols)]
        for row in range(product.rows)
    ]


def _identity(size: int) -> _Matrix:
    return [
        [sympy.Integer(1 if row == column else 0) for column in range(size)]
        for row in range(size)
    ]


def _permutation_state(matrix: _Matrix) -> _State:
    state: _State = "equal"
    size = len(matrix)
    for row in matrix:
        for value in row:
            state = _worse(state, _binary_state(value))
    for row_index in range(size):
        state = _worse(
            state,
            _residual_state(sum(matrix[row_index], sympy.Integer(0)) - 1),
        )
    for column in range(size):
        state = _worse(
            state,
            _residual_state(
                sum((matrix[row][column] for row in range(size)), sympy.Integer(0)) - 1
            ),
        )
    return state


def _binary_state(value: sympy.Expr) -> _State:
    zero_state = _residual_state(value)
    if zero_state == "equal":
        return "equal"
    one_state = _residual_state(value - 1)
    if one_state == "equal":
        return "equal"
    if zero_state == "unequal" and one_state == "unequal":
        return "unequal"
    return "unknown"


def _unit_lower_state(matrix: _Matrix) -> _State:
    state: _State = "equal"
    for row in range(len(matrix)):
        for column in range(len(matrix[row])):
            if column == row:
                state = _worse(state, _residual_state(matrix[row][column] - 1))
            elif column > row:
                state = _worse(state, _residual_state(matrix[row][column]))
    return state


def _upper_triangular_state(matrix: _Matrix) -> _State:
    state: _State = "equal"
    for row in range(len(matrix)):
        for column in range(row):
            state = _worse(state, _residual_state(matrix[row][column]))
    return state


def _worse(left: _State, right: _State) -> _State:
    if "unequal" in {left, right}:
        return "unequal"
    if "unknown" in {left, right}:
        return "unknown"
    return "equal"


def _finish(
    ctx: EngineContext,
    *,
    operation: str,
    method: str,
    evidence: _Evidence,
    correct_reason: str,
    incorrect_reason: str,
    unknown_reason: str,
    extra: dict[str, object] | None = None,
) -> CorrectnessResult:
    details: dict[str, object] = {
        "operation": operation,
        **_evidence_details(evidence),
    }
    if extra:
        details.update(extra)
    if evidence.state == "equal":
        return ctx.result("correct", correct_reason, method, **details)
    if evidence.state == "unequal":
        return ctx.result("incorrect", incorrect_reason, method, **details)
    return ctx.result("unknown", unknown_reason, method, **details)


def _evidence_details(evidence: _Evidence) -> dict[str, object]:
    details: dict[str, object] = {
        "cells_checked": evidence.cells_checked,
        "nonzero_cells": evidence.nonzero_cells,
        "unresolved_cells": evidence.unresolved_cells,
    }
    if evidence.first_cell is not None:
        details["first_residual_cell"] = list(evidence.first_cell)
    if evidence.first_residual is not None:
        text = sympy.sstr(evidence.first_residual)
        details["first_residual"] = text[:_MAX_RESIDUAL_TEXT]
    return details


def _wrong_answer_kind(
    ctx: EngineContext,
    *,
    operation: str,
    method: str,
    expected: str,
    actual: str,
) -> CorrectnessResult:
    return ctx.result(
        "unsupported",
        f"candidate answer kind must be {expected}",
        method,
        operation=operation,
        expected_kind=expected,
        candidate_kind=actual,
    )


def _wrong_shape(
    ctx: EngineContext,
    *,
    operation: str,
    method: str,
    expected: tuple[int, int],
    dimensions: list[int] | list[list[int]],
    label: str = "candidate matrix",
) -> CorrectnessResult:
    return ctx.result(
        "incorrect",
        f"{label} shape does not match required {expected[0]}x{expected[1]}",
        method,
        operation=operation,
        expected_dimensions=[expected[0], expected[1]],
        candidate_dimensions=dimensions,
    )


def _has_shape(matrix: list[list[Expr]], rows: int, columns: int) -> bool:
    return len(matrix) == rows and all(len(row) == columns for row in matrix)


def _dimensions(matrix: list[list[Expr]] | None) -> list[int]:
    if not matrix:
        return [0, 0]
    return [len(matrix), len(matrix[0])]


def _state_label(state: _State) -> str:
    return {"equal": "valid", "unequal": "invalid", "unknown": "unknown"}[state]
