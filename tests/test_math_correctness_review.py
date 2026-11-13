"""Regression coverage for independently reproduced review findings."""

import pytest

from edcraft_validator.application.math_correctness import check_math_correctness
from edcraft_validator.application.math_correctness_sampling import (
    qualify_math_template,
)


def num(n):
    return {"num": str(n)}


def test_answer_kind_mismatch_uses_one_unsupported_policy():
    for problem in [
        {"operation": "evaluate", "expression": num(1)},
        {"operation": "determinant", "matrix": [[num(1)]]},
    ]:
        result = check_math_correctness({"problem": problem, "answer": {"kind": "set"}})
        assert result.outcome == "unsupported"


def test_qualification_accepts_validates_dict_settings():
    template = {
        "request": {
            "problem": {"operation": "evaluate", "expression": {"param": "a"}},
            "answer": {"expression": {"param": "a"}},
        },
        "parameters": [{"name": "a", "minimum": 1, "maximum": 10}],
    }
    result = qualify_math_template(template, settings={"max_examples": 2, "seed": 42})
    assert result["status"] == "passed"
    assert result["cases_checked"] == 2
    assert result["duration_ms"] > 0
    assert (
        qualify_math_template(template, settings={"max_examples": 0})["status"]
        == "error"
    )


def test_inconsistent_linear_system_is_outside_unique_tuple_scope():
    x, y = {"sym": "x"}, {"sym": "y"}
    lhs = {"op": "add", "args": [x, y]}
    result = check_math_correctness(
        {
            "problem": {
                "operation": "solve",
                "symbols": [{"name": "x"}, {"name": "y"}],
                "solve_for": ["x", "y"],
                "relations": [{"lhs": lhs, "rhs": num(1)}, {"lhs": lhs, "rhs": num(2)}],
            },
            "answer": {"kind": "tuple", "items": [num(0), num(1)]},
        }
    )
    assert result.outcome == "unsupported"


@pytest.mark.parametrize(
    "extra",
    [
        {"matrix": [[num(1)]]},
        {"lower": num(0)},
        {"upper": num(1)},
        {"order": 2},
    ],
)
def test_irrelevant_problem_payload_is_not_silently_ignored(extra):
    result = check_math_correctness(
        {
            "problem": {"operation": "evaluate", "expression": num(1), **extra},
            "answer": {"expression": num(1)},
        }
    )
    assert result.outcome == "error"


def operation(name, *args):
    return {"op": name, "args": list(args)}


def scalar(operation_name, source, candidate, variable=None):
    problem = {
        "operation": operation_name,
        "expression": source,
        "symbols": [{"name": "x"}],
    }
    if variable is not None:
        problem["variable"] = variable
    return check_math_correctness(
        {"problem": problem, "answer": {"expression": candidate}}
    )


def test_fractional_powers_use_one_consistent_real_branch():
    x = {"sym": "x"}
    power = operation("pow", x, num("2/3"))
    absolute = operation("pow", operation("abs", x), num("2/3"))
    assert scalar("simplify", power, absolute).outcome == "correct"
    cube = operation("pow", x, num("1/3"))
    derivative = operation("div", num(1), operation("mul", num(3), absolute))
    assert scalar("differentiate", cube, derivative, variable="x").outcome == "correct"


def test_tangent_and_sine_domains_accept_standard_correct_answers():
    x = {"sym": "x"}
    tangent = operation("tan", x)
    derivative = operation("add", num(1), operation("pow", tangent, num(2)))
    assert (
        scalar("differentiate", tangent, derivative, variable="x").outcome == "correct"
    )
    sine = operation("sin", x)
    identity = operation(
        "div",
        operation("sub", num(1), operation("pow", operation("cos", x), num(2))),
        sine,
    )
    assert scalar("simplify", identity, sine).outcome == "correct"


def test_tangent_antiderivative_covers_every_defined_component():
    x = {"sym": "x"}
    primitive = operation(
        "mul", num(-1), operation("log", operation("abs", operation("cos", x)))
    )
    assert (
        scalar("antiderivative", operation("tan", x), primitive, variable="x").outcome
        == "correct"
    )


def test_finite_rational_answer_to_infinite_inequality_has_a_counterexample():
    x = {"sym": "x"}
    result = check_math_correctness(
        {
            "problem": {
                "operation": "solve",
                "symbols": [{"name": "x"}],
                "solve_for": ["x"],
                "domain": "rational",
                "relations": [
                    {"kind": "le", "lhs": operation("pow", x, num(2)), "rhs": num(2)}
                ],
            },
            "answer": {"kind": "set", "items": [num(-1), num(0), num(1)]},
        }
    )
    assert result.outcome == "incorrect"


def test_solver_uses_the_same_fractional_power_branch_as_scalar_checks():
    request = {
        "problem": {
            "operation": "solve",
            "symbols": [{"name": "x"}],
            "solve_for": ["x"],
            "relations": [
                {
                    "lhs": operation("pow", {"sym": "x"}, num("2/3")),
                    "rhs": num(1),
                }
            ],
        },
        "answer": {"kind": "set", "items": [num(1)]},
    }
    assert check_math_correctness(request).outcome == "correct"
    request["answer"]["items"].append(num(-1))
    assert check_math_correctness(request).outcome == "incorrect"
