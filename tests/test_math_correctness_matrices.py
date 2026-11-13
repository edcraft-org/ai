"""Focused tests for exact matrix-operation correctness."""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any

import pytest

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    EngineUnsupported,
)
from edcraft_validator.domains.math.engine.matrices import check_matrices


def _num(value: int | str | Fraction) -> dict[str, object]:
    return {"num": str(value)}


def _op(name: str, *args: dict[str, object]) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def _sqrt(value: int | str | Fraction) -> dict[str, object]:
    return _op("sqrt", _num(value))


def _matrix(rows: list[list[Any]]) -> list[list[dict[str, object]]]:
    return [
        [cell if isinstance(cell, dict) else _num(cell) for cell in row] for row in rows
    ]


def _matrix_answer(rows: list[list[Any]]) -> dict[str, object]:
    return {"kind": "matrix", "matrix": _matrix(rows)}


def _expression_answer(expression: dict[str, object]) -> dict[str, object]:
    return {"kind": "expression", "expression": expression}


def _lu_answer(
    permutation: list[list[Any]],
    lower: list[list[Any]],
    upper: list[list[Any]],
) -> dict[str, object]:
    return {
        "kind": "lu",
        "permutation": _matrix(permutation),
        "lower": _matrix(lower),
        "upper": _matrix(upper),
    }


def _run(
    operation: str,
    matrix: list[list[Any]],
    answer: dict[str, object],
    *,
    right_matrix: list[list[Any]] | None = None,
    symbols: list[dict[str, object]] | None = None,
):
    problem: dict[str, object] = {
        "operation": operation,
        "matrix": _matrix(matrix),
    }
    if right_matrix is not None:
        problem["right_matrix"] = _matrix(right_matrix)
    if symbols is not None:
        problem["symbols"] = symbols
    request = CorrectnessRequest.model_validate({"problem": problem, "answer": answer})
    return check_matrices(EngineContext.create(request))


def test_rectangular_matrix_multiplication_is_exact() -> None:
    left = [
        [1, 2, 3, 0, 1],
        [4, 5, 6, 1, 0],
        [7, 8, 9, 2, 1],
    ]
    right = [
        [1, 0],
        [0, 1],
        [1, 1],
        [2, -1],
        [-1, 2],
    ]
    expected = [[3, 7], [12, 10], [19, 17]]

    result = _run(
        "matrix-multiply",
        left,
        _matrix_answer(expected),
        right_matrix=right,
    )
    assert result.outcome == "correct", result.reason
    assert result.details["nonzero_cells"] == 0
    json.dumps(result.details)

    wrong = [row[:] for row in expected]
    wrong[0][0] = 4
    result = _run(
        "matrix-multiply",
        left,
        _matrix_answer(wrong),
        right_matrix=right,
    )
    assert result.outcome == "incorrect"
    assert result.details["nonzero_cells"] >= 1
    json.dumps(result.details)


def test_matrix_multiplication_rejects_mismatched_inner_dimensions() -> None:
    with pytest.raises(EngineUnsupported):
        _run(
            "matrix-multiply",
            [[1, 2]],
            _matrix_answer([[1], [2]]),
            right_matrix=[[1], [2], [3]],
        )


def test_matrix_multiplication_candidate_shape_is_incorrect() -> None:
    result = _run(
        "matrix-multiply",
        [[1, 2], [3, 4]],
        _matrix_answer([[2, 1, 0], [4, 3, 0]]),
        right_matrix=[[0, 1], [1, 0]],
    )
    assert result.outcome == "incorrect"
    assert "shape" in result.reason

    result = _run(
        "matrix-multiply",
        [[1, 2], [3, 4]],
        {"kind": "expression", "expression": _num(1)},
        right_matrix=[[0, 1], [1, 0]],
    )
    assert result.outcome == "unsupported"


def test_determinant_is_exact_for_4x4_and_5x5() -> None:
    four = [
        [2, 1, 0, 3],
        [1, -1, 2, 0],
        [3, 0, 1, 1],
        [0, 2, 1, 4],
    ]
    result = _run("determinant", four, _expression_answer(_num(-16)))
    assert result.outcome == "correct", result.reason
    json.dumps(result.details)

    five = [
        [2, 1, 0, 0, 0],
        [1, 3, 1, 0, 0],
        [0, 1, 4, 1, 0],
        [0, 0, 1, 5, 1],
        [0, 0, 0, 1, 6],
    ]
    result = _run("determinant", five, _expression_answer(_num(492)))
    assert result.outcome == "correct", result.reason


def test_determinant_accepts_exact_radical_forms_but_not_tiny_residuals() -> None:
    matrix = [[_sqrt(2), 0], [0, _sqrt(2)]]
    equivalent = _op("div", _sqrt(8), _sqrt(2))
    result = _run("determinant", matrix, _expression_answer(equivalent))
    assert result.outcome == "correct", result.reason

    tiny_off_by = Fraction(-16) + Fraction(1, 10**30)
    result = _run(
        "determinant",
        [
            [2, 1, 0, 3],
            [1, -1, 2, 0],
            [3, 0, 1, 1],
            [0, 2, 1, 4],
        ],
        _expression_answer(_num(tiny_off_by)),
    )
    assert result.outcome == "incorrect"
    assert result.details["nonzero_cells"] == 1


def test_singular_determinant_zero_is_correct() -> None:
    singular = [
        [1, 2, 3, 4],
        [2, 4, 6, 8],
        [0, 1, 0, 1],
        [1, 1, 1, 1],
    ]
    result = _run("determinant", singular, _expression_answer(_num(0)))
    assert result.outcome == "correct", result.reason

    result = _run(
        "determinant",
        singular,
        _expression_answer(_num(Fraction(1, 10**30))),
    )
    assert result.outcome == "incorrect"


def test_determinant_requires_an_expression_answer() -> None:
    result = _run(
        "determinant",
        [[1, 2], [3, 4]],
        _matrix_answer([[-2]]),
    )
    assert result.outcome == "unsupported"
    assert "expression" in result.reason


def test_determinant_requires_square_problem_matrix() -> None:
    with pytest.raises(EngineUnsupported):
        _run(
            "determinant",
            [[1, 2, 3], [4, 5, 6]],
            _expression_answer(_num(0)),
        )


def test_one_by_one_operations_are_supported() -> None:
    result = _run("determinant", [[7]], _expression_answer(_num(7)))
    assert result.outcome == "correct", result.reason

    result = _run("inverse", [[7]], _matrix_answer([[Fraction(1, 7)]]))
    assert result.outcome == "correct", result.reason

    result = _run(
        "lu",
        [[7]],
        _lu_answer([[1]], [[1]], [[7]]),
    )
    assert result.outcome == "correct", result.reason


def test_inverse_4x4_verifies_both_exact_products() -> None:
    matrix = [
        [4, 7, 2, 1],
        [3, 6, 1, 0],
        [2, 5, 3, 1],
        [1, 2, 0, 5],
    ]
    inverse = [
        ["67/47", "-53/47", "-27/47", "-8/47"],
        ["-36/47", "39/47", "11/47", "5/47"],
        ["15/47", "-28/47", "15/47", "-6/47"],
        ["1/47", "-5/47", "1/47", "9/47"],
    ]
    result = _run("inverse", matrix, _matrix_answer(inverse))
    assert result.outcome == "correct", result.reason
    assert result.details["nonzero_cells"] == 0
    json.dumps(result.details)

    wrong = [row[:] for row in inverse]
    wrong[0][0] = Fraction(67, 47) + Fraction(1, 10**30)
    result = _run("inverse", matrix, _matrix_answer(wrong))
    assert result.outcome == "incorrect"

    result = _run("inverse", matrix, _matrix_answer([[1, 0], [0, 1]]))
    assert result.outcome == "incorrect"
    assert "shape" in result.reason


def test_inverse_accepts_irrationals_and_rejects_singular_problem() -> None:
    matrix = [[2, 0], [0, _sqrt(2)]]
    inverse = [[Fraction(1, 2), 0], [0, _op("div", _num(1), _sqrt(2))]]
    result = _run("inverse", matrix, _matrix_answer(inverse))
    assert result.outcome == "correct", result.reason

    with pytest.raises(EngineUnsupported):
        _run(
            "inverse",
            [[1, 2], [2, 4]],
            _matrix_answer([[1, 0], [0, 1]]),
        )

    result = _run(
        "inverse",
        [[1, 2], [3, 4]],
        _expression_answer(_num(1)),
    )
    assert result.outcome == "unsupported"


def test_inverse_requires_square_problem_matrix() -> None:
    with pytest.raises(EngineUnsupported):
        _run(
            "inverse",
            [[1, 2, 3], [4, 5, 6]],
            _matrix_answer([[1, 0], [0, 1]]),
        )


def test_lu_accepts_alternative_valid_pivots() -> None:
    matrix = [[2, 1], [4, 3]]

    standard = _lu_answer(
        [[1, 0], [0, 1]],
        [[1, 0], [2, 1]],
        [[2, 1], [0, 1]],
    )
    result = _run("lu", matrix, standard)
    assert result.outcome == "correct", result.reason

    alternate = _lu_answer(
        [[0, 1], [1, 0]],
        [[1, 0], [Fraction(1, 2), 1]],
        [[4, 3], [0, Fraction(-1, 2)]],
    )
    result = _run("lu", matrix, alternate)
    assert result.outcome == "correct", result.reason
    json.dumps(result.details)


def test_lu_rejects_structurally_invalid_decompositions() -> None:
    matrix = [[2, 1], [4, 3]]
    permutation = [[1, 0], [0, 1]]
    lower = [[1, 0], [2, 1]]
    upper = [[2, 1], [0, 1]]

    # Same product, but L is not unit lower triangular.
    scaled = _lu_answer(
        permutation,
        [[2, 0], [4, 2]],
        [[1, Fraction(1, 2)], [0, Fraction(1, 2)]],
    )
    assert _run("lu", matrix, scaled).outcome == "incorrect"

    not_upper = _lu_answer(
        permutation,
        lower,
        [[2, 1], [1, 1]],
    )
    assert _run("lu", matrix, not_upper).outcome == "incorrect"

    not_lower = _lu_answer(
        permutation,
        [[1, 1], [2, 1]],
        upper,
    )
    assert _run("lu", matrix, not_lower).outcome == "incorrect"

    bad_permutation = _lu_answer(
        [[1, 1], [0, 0]],
        lower,
        upper,
    )
    assert _run("lu", matrix, bad_permutation).outcome == "incorrect"

    non_binary = _lu_answer(
        [[2, -1], [0, 1]],
        lower,
        upper,
    )
    assert _run("lu", matrix, non_binary).outcome == "incorrect"

    shape_wrong = _lu_answer(
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        lower,
        upper,
    )
    shape_result = _run("lu", matrix, shape_wrong)
    assert shape_result.outcome == "incorrect"
    assert "shape" in shape_result.reason


def test_lu_4x4_and_singular_matrix() -> None:
    lower = [
        [1, 0, 0, 0],
        [Fraction(1, 2), 1, 0, 0],
        [0, Fraction(1, 3), 1, 0],
        [1, 0, Fraction(-1, 2), 1],
    ]
    upper = [
        [2, 1, 0, 1],
        [0, 3, 1, 0],
        [0, 0, 4, 1],
        [0, 0, 0, 5],
    ]
    matrix = [
        [2, 1, 0, 1],
        [1, Fraction(7, 2), 1, Fraction(1, 2)],
        [0, 1, Fraction(13, 3), 1],
        [2, 1, -2, Fraction(11, 2)],
    ]
    answer = _lu_answer(
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ],
        lower,
        upper,
    )
    result = _run("lu", matrix, answer)
    assert result.outcome == "correct", result.reason

    singular = _lu_answer(
        [[1, 0], [0, 1]],
        [[1, 0], [1, 1]],
        [[1, 1], [0, 0]],
    )
    result = _run("lu", [[1, 1], [1, 1]], singular)
    assert result.outcome == "correct", result.reason

    with pytest.raises(EngineUnsupported):
        _run(
            "lu",
            [[1, 2, 3], [4, 5, 6]],
            singular,
        )


def test_symbolic_problem_entries_are_rejected_before_cancellation() -> None:
    symbols = [{"name": "x", "kind": "given", "domain": "real"}]

    with pytest.raises(EngineUnsupported):
        _run(
            "determinant",
            [
                [{"op": "sub", "args": [{"sym": "x"}, {"sym": "x"}]}, 0],
                [0, 1],
            ],
            _expression_answer(_num(1)),
            symbols=symbols,
        )

    with pytest.raises(EngineUnsupported):
        _run(
            "determinant",
            [[_sqrt(-1), 0], [0, 1]],
            _expression_answer(_num(1)),
        )

    with pytest.raises(EngineUnsupported):
        _run(
            "determinant",
            [[_op("div", _num(1), _num(0)), 0], [0, 1]],
            _expression_answer(_num(1)),
        )


def test_unresolved_candidate_comparison_is_unknown() -> None:
    symbols = [{"name": "x", "kind": "given", "domain": "real"}]
    result = _run(
        "determinant",
        [[1, 0], [0, 2]],
        _expression_answer({"sym": "x"}),
        symbols=symbols,
    )
    assert result.outcome == "unknown"
    assert result.details["unresolved_cells"] == 1
    json.dumps(result.details)


def test_eight_by_eight_multiplication_stays_exact() -> None:
    size = 8
    diagonal = [[i + 1 if i == j else 0 for j in range(size)] for i in range(size)]
    identity = [[1 if i == j else 0 for j in range(size)] for i in range(size)]
    result = _run(
        "matrix-multiply",
        identity,
        _matrix_answer(diagonal),
        right_matrix=diagonal,
    )
    assert result.outcome == "correct", result.reason
