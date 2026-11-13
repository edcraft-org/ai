"""LU answers follow ``P * A = L * U`` (not scipy's ``A = P * L * U``)."""

from __future__ import annotations

from edcraft_validator.application.math_correctness import check_math_correctness
from edcraft_validator.domains.math.engine.dispatch import LU_CONVENTION

# A three-cycle permutation: P != P^T, unlike the two-element swap used in the
# existing matrix tests, so a transposed convention cannot pass by accident.
CYCLE = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def _matrix(rows: list[list[int]]) -> list[list[dict[str, str]]]:
    return [[{"num": str(value)} for value in row] for row in rows]


def _check(permutation: list[list[int]]):
    return check_math_correctness(
        {
            "problem": {"operation": "lu", "matrix": _matrix(CYCLE)},
            "answer": {
                "kind": "lu",
                "permutation": _matrix(permutation),
                "lower": _matrix(IDENTITY),
                "upper": _matrix(IDENTITY),
            },
        }
    )


def test_lu_uses_p_a_equals_l_u_for_a_three_cycle():
    accepted = _check([[0, 0, 1], [1, 0, 0], [0, 1, 0]])  # CYCLE^T
    assert accepted.outcome == "correct", accepted.reason
    assert accepted.details["lu_convention"] == LU_CONVENTION
    assert LU_CONVENTION == "P * A = L * U"

    # CYCLE appears in scipy's transposed convention: A = P * L * U with
    # P = CYCLE, L = U = I.  It is not a valid ``P * A = L * U`` answer.
    rejected = _check(CYCLE)
    assert rejected.outcome == "incorrect", rejected.reason
    assert rejected.details["lu_convention"] == LU_CONVENTION
