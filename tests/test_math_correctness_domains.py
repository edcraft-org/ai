"""Cross-handler domain and policy regressions through the public worker."""

import pytest

from edcraft_validator.application.math_correctness import check_math_correctness


def num(n):
    return {"num": str(n)}


def op(name, *args):
    return {"op": name, "args": list(args)}


X = {"sym": "x"}


def check(expression, answer, operation="simplify", **problem):
    return check_math_correctness(
        {
            "problem": {
                "operation": operation,
                "expression": expression,
                "symbols": [{"name": "x"}],
                **problem,
            },
            "answer": {"expression": answer},
        }
    )


def test_exact_nonzero_residual_is_not_tolerance_equal():
    assert check(num(0), num("1/10000000000000")).outcome == "incorrect"


def test_form_is_intentionally_not_assessed():
    polynomial = op("sub", op("pow", X, num(2)), num(1))
    assert check(polynomial, polynomial, operation="factor").outcome == "correct"
    product = op("mul", op("sub", X, num(1)), op("add", X, num(1)))
    assert check(product, product, operation="expand").outcome == "correct"


def test_candidate_cannot_introduce_a_domain_hole():
    assert check(num(1), op("div", X, X)).outcome == "incorrect"
    assert check(op("div", X, X), num(1)).outcome == "correct"


def test_square_root_is_not_signed_variable_on_all_reals():
    assert check(op("sqrt", op("pow", X, num(2))), X).outcome == "incorrect"


def test_extra_relational_givens_are_not_ignored():
    result = check(X, X, relations=[{"lhs": X, "rhs": num(1)}])
    assert result.outcome == "unsupported"


def test_source_and_answer_symbolic_limits_fail_safely():
    result = check(op("pow", X, X), X)
    assert result.outcome == "unsupported"


def test_limits_and_eigenvalues_have_not_been_added():
    for operation in ("limit", "eigenvalues"):
        assert check(X, X, operation=operation).outcome == "error"


@pytest.mark.parametrize("symbols", [[], [{"name": "x"}, {"name": "x"}]])
def test_invalid_calculus_symbol_declaration_is_an_error(symbols):
    result = check(X, num(1), operation="differentiate", variable="x", symbols=symbols)
    assert result.outcome == "error"


def test_two_argument_log_uses_value_then_base():
    # log(1, 2) is defined and equals zero; the value 1 is not an invalid base.
    result = check(op("log", num(1), num(2)), num(0))
    assert result.outcome == "correct"
