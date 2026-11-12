"""Mathematical and structural correctness of the reusable algebra kernels."""

import json
from copy import deepcopy
from fractions import Fraction

import pytest
import sympy
from hypothesis import given, settings
from hypothesis import strategies as st

from edcraft_validator.application.check_pilot import algebra_checks as checks

EXPAND = "polynomial.expand/1"
FACTOR = "polynomial.factor/1"
SQUARE = "polynomial.complete-square/1"
SYSTEM = "linear-system.unique/1"


def n(value):
    return {"num": str(value)}


def x():
    return {"sym": "x"}


def op(name, *args):
    return {"op": name, "args": list(args)}


def normalized(node):
    """The kernel serialises Expr with the default empty ``args`` list."""
    if "op" in node:
        return {"op": node["op"], "args": [normalized(arg) for arg in node["args"]]}
    return {**node, "args": []}


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


def test_intermediate_arithmetic_is_bounded_before_cancellation():
    huge = n(20)
    for _ in range(3):
        huge = op("pow", huge, n(5))
    expression = op("add", x(), op("sub", huge, huge))
    with pytest.raises(ValueError, match="arithmetic budget"):
        checks.validate_problem(
            "polynomial.expand/1",
            {"kind": "polynomial-expand", "expression": expression},
        )


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


def test_contract_specs_are_closed_and_match_concrete_problem_kinds():
    specs = {spec["contract_id"]: spec for spec in checks.CONTRACT_SPECS}
    assert set(specs) == {EXPAND, FACTOR, SQUARE, SYSTEM}
    for spec in specs.values():
        assert set(spec) == {"contract_id", "title", "summary", "kind"}
        assert spec["title"]
        assert spec["summary"]
    for contract in specs:
        for problem in checks.boundary_problems(contract):
            assert problem["kind"] == specs[contract]["kind"]
            checks.validate_problem(contract, problem)
    with pytest.raises(ValueError):
        checks.validate_problem(
            EXPAND, {"kind": "polynomial-factor", "expression": quadratic()}
        )


def test_completed_square_inner_must_be_an_explicit_monic_linear_form():
    problem = {
        "kind": "polynomial-complete-square",
        "expression": op(
            "add",
            op("pow", x(), n(2)),
            op("mul", n(4), x()),
            n(1),
        ),
    }
    accepted = [
        op("sub", op("pow", op("add", x(), n(2)), n(2)), n(3)),
        # x - (-2) is still the explicit linear form x - h with h = -2.
        op("sub", op("pow", op("sub", x(), n(-2)), n(2)), n(3)),
        # Addition is commutative, so the literal may come first.
        op("add", op("pow", op("add", n(2), x()), n(2)), n(-3)),
        # An exponent whose value is exactly two still requests a square.
        op("sub", op("pow", op("add", x(), n(2)), n("2/1")), n(3)),
    ]
    for answer in accepted:
        assert checks.check_answer(checks.SQUARE, problem, {"expression": answer})

    # Each of these is mathematically (x+2)^2 - 3 but hides the linear inner
    # expression behind cancellation, a power, a redundant product or a
    # non-monic leading sign. Structural form is part of the answer.
    hidden_inner = op(
        "sub",
        op("add", op("pow", x(), n(2)), x(), n(2)),
        op("pow", x(), n(2)),
    )
    rejected = [
        op("sub", op("pow", hidden_inner, n(2)), n(3)),
        op("sub", op("pow", op("add", x(), n(2), n(0)), n(2)), n(3)),
        op("sub", op("pow", op("mul", n(1), op("add", x(), n(2))), n(2)), n(3)),
        op("sub", op("pow", op("pow", x(), n(1)), n(2)), n(3)),
        op("add", op("pow", op("sub", n(2), x()), n(2)), n(-3)),
    ]
    for answer in rejected:
        assert not checks.check_answer(checks.SQUARE, problem, {"expression": answer})


def test_completed_square_answer_arithmetic_is_bounded_but_closed():
    # Coefficients are inside the advertised expanded-coefficient bound even
    # though literals are small. The oracle's constant is -249000, well above
    # the old 100000 candidate budget, so check/render must use the explicit
    # algebra answer budget rather than reject their own oracle.
    problem = {
        "kind": "polynomial-complete-square",
        "expression": op(
            "add",
            op("pow", x(), n(2)),
            op("mul", n(20), n(20), n("5/2"), x()),
            op("mul", n(20), n(20), n("5/2")),
        ),
    }
    validated = checks.validate_problem(SQUARE, problem)
    answer = checks.expected_answer(SQUARE, validated)
    assert normalized(answer["expression"])["args"][1] == normalized(n(-249000))
    assert checks.check_answer(SQUARE, validated, answer)
    assert "-249000" in checks.render_answer(SQUARE, answer)
    assert checks.render_problem(SQUARE, validated)


def test_factorisation_accepts_valid_scalings_signs_and_repeated_roots():
    # 2x^2 - 2 = 2(x-1)(x+1) = (2x-2)(x+1) = (x-1)(2x+2).
    problem = {
        "kind": "polynomial-factor",
        "expression": op("add", op("mul", n(2), op("pow", x(), n(2))), n(-2)),
    }
    alternatives = [
        op("mul", n(2), op("sub", x(), n(1)), op("add", x(), n(1))),
        op(
            "mul",
            op("sub", op("mul", n(2), x()), n(2)),
            op("add", x(), n(1)),
        ),
        op(
            "mul",
            op("sub", x(), n(1)),
            op("add", op("mul", n(2), x()), n(2)),
        ),
    ]
    for answer in alternatives:
        assert checks.check_answer(FACTOR, problem, {"expression": answer})

    # Repeated roots may be written as a square or as repeated factors.
    repeated = {
        "kind": "polynomial-factor",
        "expression": op("add", op("pow", x(), n(2)), op("mul", n(-2), x()), n(1)),
    }
    for answer in [
        op("pow", op("sub", x(), n(1)), n(2)),
        op("mul", op("sub", x(), n(1)), op("sub", x(), n(1))),
    ]:
        assert checks.check_answer(FACTOR, repeated, {"expression": answer})
    assert not checks.check_answer(
        FACTOR,
        repeated,
        {"expression": op("mul", op("sub", x(), n(1)), op("add", x(), n(1)))},
    )

    # Non-trivial scalar products are still genuine factorisations; a total
    # scalar of one is the identity-factor evasion and stays rejected.
    six = {
        "kind": "polynomial-factor",
        "expression": op("add", op("mul", n(6), op("pow", x(), n(2))), n(-6)),
    }
    accepted_scalars = [
        op("mul", n(2), n(3), op("sub", x(), n(1)), op("add", x(), n(1))),
        op(
            "mul",
            n(2),
            op("mul", n(3), op("sub", x(), n(1)), op("add", x(), n(1))),
        ),
    ]
    for answer in accepted_scalars:
        assert checks.check_answer(FACTOR, six, {"expression": answer})
    monic = {"kind": "polynomial-factor", "expression": quadratic()}
    identity_evasions = [
        op("mul", n(1), op("sub", x(), n(1)), op("add", x(), n(1))),
        op(
            "mul",
            n(2),
            n("1/2"),
            op("sub", x(), n(1)),
            op("add", x(), n(1)),
        ),
    ]
    for answer in identity_evasions:
        assert not checks.check_answer(FACTOR, monic, {"expression": answer})

    # An irreducible quadratic is already fully factorised over the rationals.
    irreducible = op("add", op("pow", x(), n(2)), n(1))
    assert checks.check_answer(
        FACTOR,
        {"kind": "polynomial-factor", "expression": irreducible},
        {"expression": irreducible},
    )


def test_factorisation_rejects_hidden_cancellation_and_inexplicit_factors():
    problem = {"kind": "polynomial-factor", "expression": quadratic()}
    hidden_linear = op(
        "sub",
        op("add", op("pow", x(), n(2)), x()),
        op("pow", x(), n(2)),
    )
    hidden_linear = op("add", hidden_linear, n(-1))
    assert not checks.check_answer(
        FACTOR,
        problem,
        {"expression": op("mul", hidden_linear, op("add", x(), n(1)))},
    )

    repeated = {
        "kind": "polynomial-factor",
        "expression": op("add", op("pow", x(), n(2)), op("mul", n(-2), x()), n(1)),
    }
    hidden_root = op("add", op("sub", x(), op("pow", x(), n(0))), n(0))
    assert not checks.check_answer(
        FACTOR,
        repeated,
        {"expression": op("pow", hidden_root, n(2))},
    )

    # x*x is a legitimate product of linear factors, but x*x^1 and x^0 hiding
    # inside a factor are not explicit collected factors.
    assert checks.check_answer(
        FACTOR,
        {"kind": "polynomial-factor", "expression": op("pow", x(), n(2))},
        {"expression": op("mul", x(), x())},
    )
    assert not checks.check_answer(
        FACTOR,
        {"kind": "polynomial-factor", "expression": op("pow", x(), n(2))},
        {"expression": op("pow", op("pow", x(), n(1)), n(2))},
    )


def test_expansion_requires_collected_monomials_and_explicit_powers():
    squared = op("add", op("pow", x(), n(2)), n(1))
    problem = {"kind": "polynomial-expand", "expression": squared}
    assert checks.check_answer(EXPAND, problem, {"expression": squared})
    # x^0 + x^2 is equivalent but not a collected expansion.
    assert not checks.check_answer(
        EXPAND,
        problem,
        {"expression": op("add", op("pow", x(), n(0)), op("pow", x(), n(2)))},
    )
    linear = {"kind": "polynomial-expand", "expression": op("add", x(), n(1))}
    assert not checks.check_answer(
        EXPAND,
        linear,
        {"expression": op("add", op("pow", x(), n(1)), n(1))},
    )
    # An exact integer exponent written as a rational literal is the same
    # power; the form is still an explicit monomial.
    assert checks.check_answer(
        EXPAND,
        {
            "kind": "polynomial-expand",
            "expression": op("add", op("pow", x(), n(2)), x()),
        },
        {"expression": op("add", op("pow", x(), n("2/1")), x())},
    )
    # Like terms and repeated powers are rejected even when equivalent.
    assert not checks.check_answer(
        EXPAND,
        {
            "kind": "polynomial-expand",
            "expression": op("add", op("pow", x(), n(2)), x()),
        },
        {
            "expression": op(
                "add",
                op("pow", x(), n(2)),
                op("mul", n(1), x()),
                op("mul", n(2), x()),
                op("mul", n(-2), x()),
            )
        },
    )


def test_linear_systems_use_exact_rational_solutions_and_closed_scope():
    problem = {
        "kind": "linear-system-unique",
        "matrix": [[2, 1], [1, 3]],
        "rhs": [1, 2],
    }
    expected = checks.expected_answer(SYSTEM, problem)
    assert expected == {"values": ["1/5", "3/5"]}
    assert Fraction(expected["values"][0]) == Fraction(1, 5)
    assert Fraction(expected["values"][1]) == Fraction(3, 5)
    assert checks.check_answer(SYSTEM, problem, expected)
    for equivalent in [["2/10", "6/10"], ["0.2", "0.6"]]:
        assert checks.check_answer(SYSTEM, problem, {"values": equivalent})
    assert not checks.check_answer(SYSTEM, problem, {"values": ["0.2000001", "0.6"]})
    wrongs = checks.wrong_answers(SYSTEM, problem, expected)
    assert len(wrongs) >= 5
    assert len({json.dumps(item, sort_keys=True) for item in wrongs}) == len(wrongs)
    for wrong in wrongs:
        assert not checks.check_answer(SYSTEM, problem, wrong)

    boundary = {
        "kind": "linear-system-unique",
        "matrix": [[20, 1], [19, 1]],
        "rhs": [20, 19],
    }
    boundary_answer = checks.expected_answer(SYSTEM, boundary)
    assert boundary_answer == {"values": ["1", "0"]}
    assert checks.check_answer(SYSTEM, boundary, boundary_answer)

    bad_problems = [
        {"kind": "linear-system-unique", "matrix": [[1, 2], [2, 4]], "rhs": [1, 2]},
        {"kind": "linear-system-unique", "matrix": [[1, 0], [0, 1]], "rhs": [True, 0]},
        {"kind": "linear-system-unique", "matrix": [[1.0, 0], [0, 1]], "rhs": [1, 0]},
        {"kind": "linear-system-unique", "matrix": [[21, 0], [0, 1]], "rhs": [1, 0]},
        {
            "kind": "linear-system-unique",
            "matrix": [[1, 0], [0, 1]],
            "rhs": [1, 0],
            "extra": 1,
        },
    ]
    for bad in bad_problems:
        with pytest.raises(ValueError):
            checks.validate_problem(SYSTEM, bad)
    for bad in [
        {"values": ["1"]},
        {"values": ["1", "0", "2"]},
        {"values": ["1", "0"], "kind": "x"},
        {"values": [1, 0]},
    ]:
        assert not checks.check_answer(SYSTEM, boundary, bad)


def test_algebra_scope_and_answer_budgets_fail_closed():
    for contract, kind in [
        (EXPAND, "polynomial-expand"),
        (FACTOR, "polynomial-factor"),
        (SQUARE, "polynomial-complete-square"),
    ]:
        # Non-integer expanded coefficients would make derived oracle output
        # exceed the explicit answer budget, so the contract is integer-only.
        with pytest.raises(ValueError, match="integer expanded coefficients"):
            checks.validate_problem(
                contract,
                {
                    "kind": kind,
                    "expression": op(
                        "add",
                        op("mul", n("1/20"), op("pow", x(), n(2))),
                        x(),
                        n(1),
                    ),
                },
            )
        # Degrees above the advertised limit are rejected before symbolic work.
        degree = 6 if contract == EXPAND else 3
        with pytest.raises(ValueError):
            checks.validate_problem(
                contract,
                {"kind": kind, "expression": op("pow", x(), n(degree))},
            )

    problem = {"kind": "polynomial-expand", "expression": op("add", x(), n(1))}
    assert not checks.check_answer(
        EXPAND,
        problem,
        {"expression": op("add", x(), n("1" * 33))},
    )
    assert not checks.check_answer(
        EXPAND,
        problem,
        {"expression": {"num": "1e3"}},
    )
    assert not checks.check_answer(
        EXPAND,
        problem,
        {"expression": {"num": "nan"}},
    )
    assert not checks.check_answer(
        EXPAND,
        problem,
        {"expression": {"num": True}},
    )
    deep = x()
    for _ in range(20):
        deep = op("add", deep, n(1))
    assert not checks.check_answer(EXPAND, problem, {"expression": deep})
    assert not checks.check_answer(
        EXPAND,
        problem,
        {"expression": op("add", x(), n(1)), "extra": True},
    )


def test_expected_answers_are_exact_independent_structural_oracles(monkeypatch):
    expand_problem = {
        "kind": "polynomial-expand",
        "expression": op("mul", op("sub", x(), n(1)), op("add", x(), n(1))),
    }
    assert normalized(checks.expected_answer(EXPAND, expand_problem)["expression"]) == (
        normalized(op("add", op("pow", x(), n(2)), n(-1)))
    )

    factor_problem = {"kind": "polynomial-factor", "expression": quadratic()}
    assert normalized(
        checks.expected_answer(FACTOR, factor_problem)["expression"]
    ) == normalized(op("mul", op("sub", x(), n(1)), op("add", x(), n(1))))

    square_problem = {
        "kind": "polynomial-complete-square",
        "expression": op("add", op("pow", x(), n(2)), op("mul", n(4), x()), n(1)),
    }
    assert normalized(
        checks.expected_answer(SQUARE, square_problem)["expression"]
    ) == normalized(op("add", op("pow", op("add", x(), n(2)), n(2)), n(-3)))

    system_problem = {
        "kind": "linear-system-unique",
        "matrix": [[2, 1], [1, -1]],
        "rhs": [5, 1],
    }
    assert checks.expected_answer(SYSTEM, system_problem) == {"values": ["2", "1"]}

    # The oracle is coefficient/rational arithmetic, not a SymPy solve/factor.
    def forbidden(*_args, **_kwargs):
        raise AssertionError("the independent oracle must not call SymPy solvers")

    for name in ("solve", "factor", "diff", "integrate"):
        monkeypatch.setattr(sympy, name, forbidden)
    for contract, problem in [
        (EXPAND, expand_problem),
        (FACTOR, factor_problem),
        (SQUARE, square_problem),
        (SYSTEM, system_problem),
    ]:
        assert checks.expected_answer(contract, problem)


@pytest.mark.parametrize("contract", [EXPAND, FACTOR, SQUARE, SYSTEM])
def test_boundary_wrong_answers_are_distinct_and_genuinely_wrong(contract):
    for problem in checks.boundary_problems(contract):
        answer = checks.expected_answer(contract, problem)
        assert checks.check_answer(contract, problem, answer)
        assert checks.render_problem(contract, problem)
        assert checks.render_answer(contract, answer)
        wrongs = checks.wrong_answers(contract, problem, answer)
        assert len(wrongs) >= 5
        assert len({json.dumps(item, sort_keys=True) for item in wrongs}) == len(wrongs)
        for wrong in wrongs:
            assert not checks.check_answer(contract, problem, wrong)


@pytest.mark.parametrize("contract", [EXPAND, FACTOR, SQUARE, SYSTEM])
@settings(max_examples=25, deadline=None)
@given(data=st.data())
def test_every_strategy_problem_round_trips_through_the_oracle(contract, data):
    problem = data.draw(checks.problem_strategy(contract))
    checks.validate_problem(contract, problem)
    answer = checks.expected_answer(contract, problem)
    assert checks.check_answer(contract, problem, answer)
    assert checks.render_problem(contract, problem)
    assert checks.render_answer(contract, answer)
    for wrong in checks.wrong_answers(contract, problem, answer):
        assert not checks.check_answer(contract, problem, wrong)
