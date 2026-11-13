"""Independent property-based oracles across the broader engine input scope."""

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest
from edcraft_validator.domains.math.engine.dispatch import check_in_process

X = {"sym": "x"}


def num(value):
    return {"num": str(value)}


def op(name, *args):
    return {"op": name, "args": list(args)}


def run(problem, answer):
    return check_in_process(
        CorrectnessRequest.model_validate({"problem": problem, "answer": answer})
    ).outcome


def polynomial(coefficients):
    terms = [
        op("mul", num(c), op("pow", X, num(i))) for i, c in enumerate(coefficients)
    ]
    return op("add", *terms)


@settings(max_examples=20, deadline=None, database=None, derandomize=True)
@given(st.lists(st.integers(-20, 20), min_size=7, max_size=13))
def test_broader_polynomial_derivatives_against_coefficient_reference(coefficients):
    expected = [i * coefficient for i, coefficient in enumerate(coefficients)][1:]
    problem = {
        "operation": "differentiate",
        "symbols": [{"name": "x"}],
        "variable": "x",
        "expression": polynomial(coefficients),
    }
    correct = polynomial(expected)
    assert run(problem, {"expression": correct}) == "correct"
    assert run(problem, {"expression": op("add", correct, num(1))}) == "incorrect"


@settings(max_examples=20, deadline=None, database=None, derandomize=True)
@given(st.lists(st.integers(-8, 8), min_size=1, max_size=4))
def test_constructed_polynomial_root_sets_against_factor_reference(roots):
    factors = [op("sub", X, num(root)) for root in roots]
    problem = {
        "operation": "solve",
        "symbols": [{"name": "x"}],
        "solve_for": ["x"],
        "relations": [{"lhs": op("mul", *factors), "rhs": num(0)}],
    }
    unique = sorted(set(roots))
    answer = {"kind": "set", "items": [num(root) for root in unique]}
    assert run(problem, answer) == "correct"
    assert (
        run(problem, {"kind": "set", "items": [num(root) for root in unique[1:]]})
        == "incorrect"
    )


@settings(max_examples=20, deadline=None, database=None, derandomize=True)
@given(st.integers(-10, 10), st.integers(1, 10), st.booleans())
def test_quadratic_inequality_endpoints_against_sign_reference(lower, width, closed):
    upper = lower + width
    problem = {
        "operation": "solve",
        "symbols": [{"name": "x"}],
        "solve_for": ["x"],
        "relations": [
            {
                "kind": "le" if closed else "lt",
                "lhs": op("mul", op("sub", X, num(lower)), op("sub", X, num(upper))),
                "rhs": num(0),
            }
        ],
    }
    bounds = {
        "lower": num(lower),
        "upper": num(upper),
        "lower_open": not closed,
        "upper_open": not closed,
    }
    assert run(problem, {"kind": "set", "intervals": [bounds]}) == "correct"
    wrong = {**bounds, "upper_open": closed}
    assert run(problem, {"kind": "set", "intervals": [wrong]}) == "incorrect"


@st.composite
def matrix_products(draw):
    rows, inner, columns = [draw(st.integers(1, 4)) for _ in range(3)]
    value = st.integers(-10, 10).map(lambda n: Fraction(n, 3))
    left = draw(
        st.lists(
            st.lists(value, min_size=inner, max_size=inner),
            min_size=rows,
            max_size=rows,
        )
    )
    right = draw(
        st.lists(
            st.lists(value, min_size=columns, max_size=columns),
            min_size=inner,
            max_size=inner,
        )
    )
    expected = [
        [
            sum((left[i][k] * right[k][j] for k in range(inner)), Fraction(0))
            for j in range(columns)
        ]
        for i in range(rows)
    ]
    return left, right, expected


@settings(max_examples=20, deadline=None, database=None, derandomize=True)
@given(matrix_products())
def test_rational_matrix_products_against_fraction_reference(data):
    left, right, expected = data

    def wire(matrix):
        return [[num(cell) for cell in row] for row in matrix]

    problem = {
        "operation": "matrix-multiply",
        "matrix": wire(left),
        "right_matrix": wire(right),
    }
    assert run(problem, {"kind": "matrix", "matrix": wire(expected)}) == "correct"
    expected[0][0] += 1
    assert run(problem, {"kind": "matrix", "matrix": wire(expected)}) == "incorrect"
