"""Independent boundary probes for the expanded mathematics contracts."""

import pytest

from edcraft_validator.application.check_pilot import calculus_checks as calculus
from edcraft_validator.application.check_pilot import matrix_checks as matrices


def test_inverse_oracle_answer_is_admitted_at_supported_integer_boundary():
    problem = {
        "kind": "matrix_inverse",
        "matrix": [["997", "1", "1"], ["1", "991", "1"], ["1", "1", "983"]],
    }
    answer = matrices.expected_answer("matrix.inverse/1", problem)
    assert matrices.check_answer("matrix.inverse/1", problem, answer)


def test_inverse_oracle_answer_is_admitted_with_distinct_rational_denominators():
    problem = {
        "kind": "matrix_inverse",
        "matrix": [
            ["997/97", "991/89", "983/83"],
            ["977/79", "971/73", "967/71"],
            ["953/67", "947/61", "941/59"],
        ],
    }
    answer = matrices.expected_answer("matrix.inverse/1", problem)
    assert matrices.check_answer("matrix.inverse/1", problem, answer)


def test_inverse_answer_budget_covers_coprime_denominators_without_cancellation():
    problem = {
        "kind": "matrix_inverse",
        "matrix": [
            ["309/97", "-772/89", "-949/83"],
            ["518/79", "-437/73", "-499/71"],
            ["-543/67", "-715/61", "508/59"],
        ],
    }
    answer = matrices.expected_answer("matrix.inverse/1", problem)
    assert matrices.check_answer("matrix.inverse/1", problem, answer)


def test_integral_oracle_answer_is_admitted_at_supported_rational_boundary():
    problem = {
        "kind": "polynomial_definite_integral",
        "coefficients": [
            "9999/997",
            "9998/991",
            "9997/983",
            "9996/977",
            "9995/971",
            "9994/967",
        ],
        "lower": "-999/991",
        "upper": "997/983",
    }
    answer = calculus.expected_answer("polynomial.definite-integral/1", problem)
    assert calculus.check_answer("polynomial.definite-integral/1", problem, answer)


@pytest.mark.parametrize("leaf", [{"num": "9" * 100}, {"param": "unbound"}])
def test_differentiation_rejects_unbounded_or_unbound_leaves_before_execution(leaf):
    with pytest.raises(ValueError):
        calculus.validate_problem(
            "expression.differentiate/1",
            {
                "kind": "expression_differentiate",
                "expression": {"op": "add", "args": [{"sym": "x"}, leaf]},
                "symbols": [{"name": "x", "positive": False, "nonzero": False}],
            },
        )


def test_differentiation_renders_nonzero_domain_assumption():
    problem = {
        "kind": "expression_differentiate",
        "expression": {"op": "div", "args": [{"num": "1"}, {"sym": "x"}]},
        "symbols": [{"name": "x", "positive": False, "nonzero": True}],
    }
    text = calculus.render_problem("expression.differentiate/1", problem)
    assert any(marker in text for marker in ("!= 0", "≠ 0", "nonzero", "non-zero"))


def test_derivative_validation_bounds_arithmetic_before_constant_cancellation():
    huge = {"num": "20"}
    for _ in range(3):
        huge = {"op": "pow", "args": [huge, {"num": "5"}]}
    problem = {
        "kind": "expression_differentiate",
        "expression": {
            "op": "mul",
            "args": [
                {"sym": "x"},
                {"op": "sub", "args": [huge, huge]},
            ],
        },
        "symbols": [{"name": "x", "positive": False, "nonzero": False}],
    }
    with pytest.raises(ValueError, match="arithmetic budget"):
        calculus.validate_problem("expression.differentiate/1", problem)


@pytest.mark.parametrize("operation", ["log", "div"])
def test_subtracting_positive_expressions_does_not_prove_a_domain(operation):
    # Positive x does not make 1-(x-1) positive or nonzero: it vanishes at 2.
    denominator = {
        "op": "sub",
        "args": [
            {"num": "1"},
            {"op": "sub", "args": [{"sym": "x"}, {"num": "1"}]},
        ],
    }
    expression = (
        {"op": "log", "args": [denominator]}
        if operation == "log"
        else {"op": "div", "args": [{"num": "1"}, denominator]}
    )
    with pytest.raises(ValueError):
        calculus.validate_problem(
            "expression.differentiate/1",
            {
                "kind": "expression_differentiate",
                "expression": expression,
                "symbols": [{"name": "x", "positive": True, "nonzero": True}],
            },
        )


@pytest.mark.parametrize("module", [calculus, matrices])
def test_qualification_mutations_do_not_consult_the_checker(module, monkeypatch):
    """A faulty checker must not erase the negative cases that would expose it."""
    examples = [
        (spec["contract_id"], module.boundary_problems(spec["contract_id"])[0])
        for spec in module.CONTRACT_SPECS
    ]
    answers = [
        module.expected_answer(contract, problem) for contract, problem in examples
    ]
    monkeypatch.setattr(module, "check_answer", lambda *args: True)
    for (contract, problem), answer in zip(examples, answers, strict=True):
        assert len(module.wrong_answers(contract, problem, answer)) >= 5
