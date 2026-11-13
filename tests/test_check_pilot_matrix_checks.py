"""Focused contract tests for the exact matrix check kernel."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from edcraft_validator.application.check_pilot import matrix_checks as matrices

MULTIPLY = "matrix.multiply/1"
DETERMINANT = "matrix.determinant/1"
INVERSE = "matrix.inverse/1"
LU = "matrix.lu/1"

CONTRACT_KINDS = {
    MULTIPLY: "matrix_multiply",
    DETERMINANT: "matrix_determinant",
    INVERSE: "matrix_inverse",
    LU: "matrix_lu",
}

ALL_CONTRACTS = tuple(CONTRACT_KINDS)


def _multiply_problem(
    left: list[list[str]], right: list[list[str]]
) -> dict[str, object]:
    return {"kind": "matrix_multiply", "left": left, "right": right}


def _determinant_problem(matrix: list[list[str]]) -> dict[str, object]:
    return {"kind": "matrix_determinant", "matrix": matrix}


def _inverse_problem(matrix: list[list[str]]) -> dict[str, object]:
    return {"kind": "matrix_inverse", "matrix": matrix}


def _lu_problem(matrix: list[list[str]]) -> dict[str, object]:
    return {"kind": "matrix_lu", "matrix": matrix}


def _assert_identity(matrix: list[list[str]], size: int) -> None:
    for row in range(size):
        for column in range(size):
            expected = Fraction(1) if row == column else Fraction(0)
            assert Fraction(matrix[row][column]) == expected


def test_contract_catalogue_is_closed_and_consistent() -> None:
    descriptors = {spec["contract_id"]: spec for spec in matrices.CONTRACT_SPECS}

    assert set(descriptors) == set(CONTRACT_KINDS)
    for contract_id, kind in CONTRACT_KINDS.items():
        assert descriptors[contract_id]["kind"] == kind
        assert descriptors[contract_id]["title"]
        assert descriptors[contract_id]["summary"]

    problem_kinds = {
        model.model_fields["kind"].default for model in matrices.PROBLEM_TYPES
    }
    assert problem_kinds == set(CONTRACT_KINDS.values())
    assert len(matrices.PROBLEM_TYPES) == len(CONTRACT_KINDS)


def test_matrix_multiplication_is_exact_and_shape_checked() -> None:
    problem = _multiply_problem([["1", "2"], ["3", "4"]], [["0", "1"], ["1", "0"]])
    answer = matrices.expected_answer(MULTIPLY, problem)
    assert answer["matrix"] == [["2", "1"], ["4", "3"]]
    assert matrices.check_answer(MULTIPLY, problem, answer)

    rectangular = _multiply_problem(
        [["1", "2", "3"], ["4", "5", "6"]],
        [["1", "0"], ["0", "1"], ["1", "1"]],
    )
    rectangular_answer = matrices.expected_answer(MULTIPLY, rectangular)
    assert rectangular_answer["matrix"] == [["4", "5"], ["10", "11"]]
    assert matrices.check_answer(MULTIPLY, rectangular, rectangular_answer)

    with pytest.raises(ValueError):
        matrices.validate_problem(
            MULTIPLY,
            _multiply_problem([["1", "2"]], [["1", "2"]]),
        )
    with pytest.raises(ValueError):
        matrices.validate_problem(
            MULTIPLY,
            _multiply_problem([["1", "2"]], [["1"], ["2"], ["3"]]),
        )
    assert not matrices.check_answer(
        MULTIPLY,
        problem,
        {"kind": "matrix_multiply_answer", "matrix": [["2", "1"], ["4", "4"]]},
    )


def test_determinant_is_exact_for_2x2_and_3x3() -> None:
    two = _determinant_problem([["1", "2"], ["3", "4"]])
    assert matrices.expected_answer(DETERMINANT, two)["value"] == "-2"

    three = _determinant_problem([["2", "-1", "3"], ["0", "4", "1"], ["5", "2", "-2"]])
    answer = matrices.expected_answer(DETERMINANT, three)
    assert Fraction(answer["value"]) == Fraction(-85)
    assert matrices.check_answer(DETERMINANT, three, answer)
    assert not matrices.check_answer(DETERMINANT, three, {**answer, "value": "-70"})

    singular = _determinant_problem([["1", "2"], ["2", "4"]])
    assert matrices.expected_answer(DETERMINANT, singular)["value"] == "0"

    with pytest.raises(ValueError):
        matrices.validate_problem(DETERMINANT, _determinant_problem([["1", "2", "3"]]))
    with pytest.raises(ValueError):
        matrices.validate_problem(
            DETERMINANT,
            _determinant_problem([["1", "2"], ["3", "4"], ["5", "6"]]),
        )


def test_matrix_inverse_rejects_singular_problems_and_candidates() -> None:
    problem = _inverse_problem([["4", "7"], ["2", "6"]])
    answer = matrices.expected_answer(INVERSE, problem)
    assert matrices.check_answer(INVERSE, problem, answer)

    product = matrices.expected_answer(
        MULTIPLY, _multiply_problem(problem["matrix"], answer["matrix"])
    )
    _assert_identity(product["matrix"], 2)

    with pytest.raises(ValueError):
        matrices.validate_problem(INVERSE, _inverse_problem([["1", "2"], ["2", "4"]]))

    assert not matrices.check_answer(
        INVERSE,
        problem,
        {"kind": "matrix_inverse_answer", "matrix": [["0", "0"], ["0", "0"]]},
    )
    wrong = {
        "kind": "matrix_inverse_answer",
        "matrix": [["0", "0"], ["0", "0"]],
    }
    assert not matrices.check_answer(INVERSE, problem, wrong)


def test_lu_verifies_pa_equals_lu_and_structural_conventions() -> None:
    # This matrix needs a row swap, so P is non-identity.
    problem = _lu_problem([["0", "2", "1"], ["1", "1", "0"], ["2", "0", "1"]])
    answer = matrices.expected_answer(LU, problem)
    assert matrices.check_answer(LU, problem, answer)
    assert answer["permutation"] != [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]]

    left = matrices.expected_answer(
        MULTIPLY, _multiply_problem(answer["permutation"], problem["matrix"])
    )
    right = matrices.expected_answer(
        MULTIPLY, _multiply_problem(answer["lower"], answer["upper"])
    )
    assert left["matrix"] == right["matrix"]

    # Product-only cheats are rejected: scaling L by 2 and U by 1/2 keeps the
    # product but breaks the unit-lower-triangular convention.
    scaled_lower = [
        [str(Fraction(cell) * 2) for cell in row] for row in answer["lower"]
    ]
    scaled_upper = [
        [str(Fraction(cell) / 2) for cell in row] for row in answer["upper"]
    ]
    scaled = {
        **answer,
        "lower": scaled_lower,
        "upper": scaled_upper,
    }
    assert not matrices.check_answer(LU, problem, scaled)

    not_unit_lower = [list(row) for row in answer["lower"]]
    not_unit_lower[0][0] = "2"
    assert not matrices.check_answer(LU, problem, {**answer, "lower": not_unit_lower})

    not_upper = [list(row) for row in answer["upper"]]
    not_upper[1][0] = "1"
    assert not matrices.check_answer(LU, problem, {**answer, "upper": not_upper})

    bad_permutation = [list(row) for row in answer["permutation"]]
    bad_permutation[0] = ["0", "0", "0"]
    assert not matrices.check_answer(
        LU, problem, {**answer, "permutation": bad_permutation}
    )

    with pytest.raises(ValueError):
        matrices.validate_problem(LU, _lu_problem([["1", "2", "3"]]))
    with pytest.raises(ValueError):
        matrices.validate_problem(
            LU,
            _lu_problem([["1", "2"], ["3", "4"], ["5", "6"]]),
        )


def test_lu_handles_identity_and_already_triangular_matrices() -> None:
    for matrix in (
        [["1", "0"], ["0", "1"]],
        [["2", "3"], ["0", "4"]],
        [["1", "2"], ["3", "4"]],
    ):
        problem = _lu_problem(matrix)
        answer = matrices.expected_answer(LU, problem)
        assert matrices.check_answer(LU, problem, answer)


def test_every_advertised_entry_bound_produces_a_valid_expected_answer() -> None:
    # Large integer entries and rational entries close to the advertised
    # input bounds must not make the oracle emit an answer outside the closed
    # answer models.
    for matrix in (
        [["997", "1", "1"], ["1", "991", "1"], ["1", "1", "983"]],
        [["1000/97", "1/3", "0"], ["1/5", "999/89", "2/7"], ["3/4", "0", "997/99"]],
        [["1000/100", "999/98"], ["-997/97", "1/2"]],
    ):
        problem = _inverse_problem(matrix)
        answer = matrices.expected_answer(INVERSE, problem)
        assert matrices.check_answer(INVERSE, problem, answer)

        determinant_problem = _determinant_problem(matrix)
        determinant_answer = matrices.expected_answer(DETERMINANT, determinant_problem)
        assert matrices.check_answer(
            DETERMINANT, determinant_problem, determinant_answer
        )


def test_wrong_answers_do_not_consult_the_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("wrong-answer construction must not call the checker")

    monkeypatch.setattr(matrices, "check_answer", fail)
    for contract_id in ALL_CONTRACTS:
        problem = matrices.boundary_problems(contract_id)[0]
        answer = matrices.expected_answer(contract_id, problem)
        assert len(matrices.wrong_answers(contract_id, problem, answer)) >= 5


def test_matrix_inputs_are_bounded_and_closed() -> None:
    bad_problems = [
        _determinant_problem([["1", "2"], ["3", "4"]]) | {"extra": True},
        _determinant_problem([["1", "2"], ["3", "not-a-number"]]),
        _determinant_problem([["1", "2"], ["3", 4]]),
        _determinant_problem([["1", "2"], ["3", "1/0"]]),
        _determinant_problem([["1", "2"], ["3", "99999999"]]),
        _determinant_problem([["1", "2"], ["3", "4", "5"]]),
        {"kind": "matrix_determinant", "matrix": []},
    ]
    for problem in bad_problems:
        with pytest.raises(ValueError):
            matrices.validate_problem(DETERMINANT, problem)

    with pytest.raises(ValueError):
        matrices.check_answer(
            DETERMINANT,
            _determinant_problem([["1", "2"], ["3", "4"]]),
            {"kind": "matrix_determinant_answer", "value": 4},
        )


@pytest.mark.parametrize("contract_id", ALL_CONTRACTS)
def test_wrong_answers_are_distinct_and_rejected(contract_id: str) -> None:
    problem = matrices.boundary_problems(contract_id)[0]
    answer = matrices.expected_answer(contract_id, problem)
    wrong = matrices.wrong_answers(contract_id, problem, answer)

    assert len(wrong) >= 5
    assert len({repr(candidate) for candidate in wrong}) == len(wrong)
    assert all(
        not matrices.check_answer(contract_id, problem, candidate)
        for candidate in wrong
    )


@pytest.mark.parametrize("contract_id", ALL_CONTRACTS)
def test_boundary_problems_validate_and_render(contract_id: str) -> None:
    problems = matrices.boundary_problems(contract_id)
    assert len(problems) >= 3
    for problem in problems:
        validated = matrices.validate_problem(contract_id, problem)
        answer = matrices.expected_answer(contract_id, validated)
        assert matrices.check_answer(contract_id, validated, answer)
        assert (
            "matrix" in matrices.render_problem(contract_id, validated).lower()
            or "det" in matrices.render_problem(contract_id, validated).lower()
        )
        assert matrices.render_answer(contract_id, answer)


@pytest.mark.parametrize("contract_id", ALL_CONTRACTS)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_problem_strategies_generate_executable_cases(
    contract_id: str, data: st.DataObject
) -> None:
    strategy = matrices.problem_strategy(contract_id)
    for _ in range(5):
        problem = data.draw(strategy)
        validated = matrices.validate_problem(contract_id, problem)
        answer = matrices.expected_answer(contract_id, validated)
        assert matrices.check_answer(contract_id, validated, answer)
        assert len(matrices.wrong_answers(contract_id, validated, answer)) >= 5


def test_unknown_contract_fails_safely() -> None:
    with pytest.raises(ValueError):
        matrices.validate_problem("matrix.nope/1", {})
    with pytest.raises(ValueError):
        matrices.expected_answer("matrix.nope/1", {})
    with pytest.raises(ValueError):
        matrices.problem_strategy("matrix.nope/1")
    with pytest.raises(ValueError):
        matrices.boundary_problems("matrix.nope/1")
