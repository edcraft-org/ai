"""Mathematical and structural correctness of the reusable algebra kernels."""

from copy import deepcopy

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from edcraft_validator.application.check_pilot import algebra_checks as checks


def n(value):
    return {"num": str(value)}


def x():
    return {"sym": "x"}


def op(name, *args):
    return {"op": name, "args": list(args)}


def quadratic():
    return op("sub", op("pow", x(), n(2)), n(1))


@pytest.mark.parametrize("spec", checks.CONTRACT_SPECS)
def test_boundary_answers_and_mutations(spec):
    contract = spec["contract_id"]
    for problem in checks.boundary_problems(contract):
        answer = checks.expected_answer(contract, problem)
        assert checks.check_answer(contract, problem, answer)
        assert checks.render_problem(contract, problem)
        assert checks.render_answer(contract, answer)
        mutations = checks.wrong_answers(contract, problem, answer)
        assert len(mutations) >= 5
        for candidate in mutations:
            assert not checks.check_answer(contract, problem, candidate)


def test_factorisation_requires_form_as_well_as_equivalence():
    contract = "polynomial.factor/1"
    problem = {"kind": "polynomial-factor", "expression": quadratic()}
    assert checks.check_answer(
        contract,
        problem,
        {"expression": op("mul", op("sub", x(), n(1)), op("add", x(), n(1)))},
    )
    assert not checks.check_answer(contract, problem, {"expression": quadratic()})
    assert not checks.check_answer(
        contract, problem, {"expression": op("mul", n(1), quadratic())}
    )
    assert not checks.check_answer(
        contract,
        problem,
        {"expression": op("mul", op("sub", x(), n(1)), op("add", x(), n(2)))},
    )


def test_irreducible_quadratic_is_already_fully_factored_over_rationals():
    expression = op("add", op("pow", x(), n(2)), n(1))
    assert checks.check_answer(
        "polynomial.factor/1",
        {"kind": "polynomial-factor", "expression": expression},
        {"expression": expression},
    )


def test_expansion_rejects_unexpanded_and_uncollected_equivalents():
    product = op("mul", op("sub", x(), n(1)), op("add", x(), n(1)))
    problem = {"kind": "polynomial-expand", "expression": product}
    contract = "polynomial.expand/1"
    assert checks.check_answer(contract, problem, {"expression": quadratic()})
    assert not checks.check_answer(contract, problem, {"expression": product})
    assert not checks.check_answer(
        contract,
        problem,
        {"expression": op("add", quadratic(), x(), op("mul", n(-1), x()))},
    )


def test_completed_square_rejects_equivalent_wrong_structure():
    problem = {
        "kind": "polynomial-complete-square",
        "expression": op("add", op("pow", x(), n(2)), op("mul", n(4), x()), n(1)),
    }
    contract = "polynomial.complete-square/1"
    correct = {"expression": op("sub", op("pow", op("add", x(), n(2)), n(2)), n(3))}
    assert checks.check_answer(contract, problem, correct)
    assert not checks.check_answer(
        contract, problem, {"expression": problem["expression"]}
    )
    assert not checks.check_answer(
        contract, problem, {"expression": op("pow", op("add", x(), n(2)), n(2))}
    )


def test_unique_system_requires_complete_ordered_tuple():
    contract = "linear-system.unique/1"
    problem = {
        "kind": "linear-system-unique",
        "matrix": [[2, 1], [1, -1]],
        "rhs": [5, 1],
    }
    assert checks.check_answer(contract, problem, {"values": ["2", "1"]})
    for values in [["1", "2"], ["2"], ["2", "1", "0"], ["2", "0"]]:
        assert not checks.check_answer(contract, problem, {"values": values})
    with pytest.raises(ValueError):
        checks.validate_problem(
            contract,
            {"kind": "linear-system-unique", "matrix": [[1, 2], [2, 4]], "rhs": [3, 6]},
        )


def test_scope_and_candidate_boundaries_fail_closed():
    contract = "polynomial.factor/1"
    problem = {"kind": "polynomial-factor", "expression": quadratic()}
    for expression in [
        op("sin", x()),
        {"sym": "y"},
        op("pow", x(), n(1000)),
        {"num": "__import__('os')"},
        {"num": "1", "unknown": 2},
    ]:
        assert not checks.check_answer(contract, problem, {"expression": expression})
    with pytest.raises(ValueError):
        checks.validate_problem("polynomial.expand/1", problem)
    tampered = deepcopy(problem)
    tampered["unknown"] = True
    with pytest.raises(ValueError):
        checks.validate_problem(contract, tampered)


@settings(max_examples=35, deadline=None)
@given(checks.problem_strategy("polynomial.factor/1"))
def test_factoring_independent_oracle_agrees_with_checker(problem):
    contract = "polynomial.factor/1"
    answer = checks.expected_answer(contract, problem)
    assert checks.check_answer(contract, problem, answer)
    assert all(
        not checks.check_answer(contract, problem, bad)
        for bad in checks.wrong_answers(contract, problem, answer)
    )


@settings(max_examples=35, deadline=None)
@given(checks.problem_strategy("linear-system.unique/1"))
def test_exact_system_oracle_agrees_with_checker(problem):
    contract = "linear-system.unique/1"
    assert checks.check_answer(
        contract, problem, checks.expected_answer(contract, problem)
    )


@pytest.mark.parametrize(
    "contract", ["polynomial.expand/1", "polynomial.complete-square/1"]
)
@settings(max_examples=35, deadline=None)
@given(data=st.data())
def test_other_algebra_oracles_and_mutations(contract, data):
    problem = data.draw(checks.problem_strategy(contract))
    answer = checks.expected_answer(contract, problem)
    assert checks.check_answer(contract, problem, answer)
    assert all(
        not checks.check_answer(contract, problem, wrong)
        for wrong in checks.wrong_answers(contract, problem, answer)
    )
