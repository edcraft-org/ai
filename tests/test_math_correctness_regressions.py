"""Adversarial cases independent of the handler implementation."""

from edcraft_validator.application.math_correctness import check_math_correctness


def n(value):
    return {"num": str(value)}


def op(name, *args):
    return {"op": name, "args": list(args)}


X = {"sym": "x"}


def solve(relations, answer):
    return check_math_correctness(
        {
            "problem": {
                "operation": "solve",
                "symbols": [{"name": "x"}],
                "solve_for": ["x"],
                "relations": relations,
            },
            "answer": answer,
        }
    )


def test_periodic_inequality_is_not_accepted_as_one_period():
    result = solve(
        [{"kind": "gt", "lhs": op("sin", X), "rhs": n(0)}],
        {"kind": "set", "intervals": [{"lower": n(0), "upper": op("acos", n(-1))}]},
    )
    assert result.outcome in {"unknown", "unsupported"}


def test_candidate_root_expression_must_be_defined_before_cancellation():
    # (1/0)^0 compiles to 1 in SymPy, but is not an admissible real AST.
    result = solve(
        [{"lhs": X, "rhs": n(1)}],
        {"kind": "set", "items": [op("pow", op("div", n(1), n(0)), n(0))]},
    )
    assert result.outcome != "correct"


def test_numeric_matrix_candidate_cannot_cancel_an_undefined_subexpression():
    result = check_math_correctness(
        {
            "problem": {"operation": "determinant", "matrix": [[n(1)]]},
            "answer": {"expression": op("pow", op("div", n(1), n(0)), n(0))},
        }
    )
    assert result.outcome != "correct"


def test_scalar_periodic_domain_is_not_truncated_to_one_period():
    source = op("log", op("sin", X))
    point = op("div", op("mul", n(5), op("acos", n(-1))), n(2))
    denominator = op("sub", X, point)
    candidate = op("mul", source, op("div", denominator, denominator))
    result = check_math_correctness(
        {
            "problem": {
                "operation": "simplify",
                "symbols": [{"name": "x"}],
                "expression": source,
            },
            "answer": {"expression": candidate},
        }
    )
    assert result.outcome != "correct"
