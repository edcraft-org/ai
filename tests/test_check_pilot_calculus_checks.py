"""Focused contract tests for the calculus check kernel.

The kernel is deliberately independent of the model-facing pipeline: each
contract exposes the agreed dict API from INTERFACE.md. These tests exercise
the oracle/checker separation, exact arithmetic and the bounded input surface.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from edcraft_validator.application.check_pilot import calculus_checks as calculus

ANTIDERIVATIVE = "polynomial.antiderivative/1"
DEFINITE = "polynomial.definite-integral/1"
DIFFERENTIATE = "expression.differentiate/1"

CONTRACT_KINDS = {
    ANTIDERIVATIVE: "polynomial_antiderivative",
    DEFINITE: "polynomial_definite_integral",
    DIFFERENTIATE: "expression_differentiate",
}

ALL_CONTRACTS = tuple(CONTRACT_KINDS)


def _num(value: object) -> dict[str, str]:
    return {"num": str(value)}


def _sym(name: str) -> dict[str, str]:
    return {"sym": name}


def _op(name: str, *args: dict[str, str]) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def _derivative_coefficients(answer: dict[str, object]) -> list[Fraction]:
    coefficients = [Fraction(value) for value in answer["coefficients"]]  # type: ignore[arg-type]
    return [
        coefficient * exponent
        for exponent, coefficient in enumerate(coefficients[1:], start=1)
    ]


def _antiderivative_problem(
    coefficients: list[str] | None = None, *, general: bool = False
) -> dict[str, object]:
    return {
        "kind": "polynomial_antiderivative",
        "coefficients": coefficients or ["1", "2", "3"],
        "general": general,
    }


def _definite_problem(
    coefficients: list[str] | None = None,
    *,
    lower: str = "0",
    upper: str = "2",
) -> dict[str, object]:
    return {
        "kind": "polynomial_definite_integral",
        "coefficients": coefficients or ["1", "0", "3"],
        "lower": lower,
        "upper": upper,
    }


def _differentiate_problem(
    expression: dict[str, object],
    *,
    symbols: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "kind": "expression_differentiate",
        "expression": expression,
        "symbols": symbols or [{"name": "x", "positive": True, "nonzero": True}],
    }


def _differentiate_answer(expression: dict[str, object]) -> dict[str, object]:
    return {"kind": "expression_differentiate_answer", "expression": expression}


def test_contract_catalogue_is_closed_and_consistent() -> None:
    descriptors = {spec["contract_id"]: spec for spec in calculus.CONTRACT_SPECS}

    assert set(descriptors) == set(CONTRACT_KINDS)
    for contract_id, kind in CONTRACT_KINDS.items():
        spec = descriptors[contract_id]
        assert spec["kind"] == kind
        assert spec["title"]
        assert spec["summary"]

    problem_kinds = {
        model.model_fields["kind"].default for model in calculus.PROBLEM_TYPES
    }
    assert problem_kinds == set(CONTRACT_KINDS.values())
    assert len(calculus.PROBLEM_TYPES) == len(CONTRACT_KINDS)


def test_antiderivative_oracle_uses_independent_derivative() -> None:
    problem = _antiderivative_problem(["4", "-3/2", "5"])
    validated = calculus.validate_problem(ANTIDERIVATIVE, problem)
    answer = calculus.expected_answer(ANTIDERIVATIVE, validated)

    derivative = _derivative_coefficients(answer)
    assert [str(value) for value in derivative] == ["4", "-3/2", "5"]
    assert calculus.check_answer(ANTIDERIVATIVE, validated, answer)


def test_antiderivative_accepts_any_additive_constant_for_a_primitive() -> None:
    problem = _antiderivative_problem(["2", "6"])
    answer = calculus.expected_answer(ANTIDERIVATIVE, problem)
    assert answer["general"] is False

    for constant in ("0", "7", "-13/5", "123456/7"):
        candidate = dict(answer)
        candidate["coefficients"] = [constant, *answer["coefficients"][1:]]
        assert calculus.check_answer(ANTIDERIVATIVE, problem, candidate)

    # A different non-constant term is a genuinely different primitive.
    wrong = dict(answer)
    wrong["coefficients"] = ["0", "3"]
    assert not calculus.check_answer(ANTIDERIVATIVE, problem, wrong)


def test_requesting_a_general_antiderivative_is_distinguished_from_one_primitive() -> (
    None
):
    primitive_problem = _antiderivative_problem(["1", "2"])
    general_problem = _antiderivative_problem(["1", "2"], general=True)

    primitive_answer = calculus.expected_answer(ANTIDERIVATIVE, primitive_problem)
    general_answer = calculus.expected_answer(ANTIDERIVATIVE, general_problem)

    assert primitive_answer["general"] is False
    assert general_answer["general"] is True
    assert "C" in calculus.render_answer(ANTIDERIVATIVE, general_answer)
    assert "C" not in calculus.render_answer(ANTIDERIVATIVE, primitive_answer)

    # The constant value is arbitrary, but the +C family marker is required.
    assert calculus.check_answer(
        ANTIDERIVATIVE,
        general_problem,
        {
            **general_answer,
            "coefficients": ["17/9", *general_answer["coefficients"][1:]],
        },
    )
    assert not calculus.check_answer(
        ANTIDERIVATIVE,
        general_problem,
        {**general_answer, "general": False},
    )
    assert not calculus.check_answer(
        ANTIDERIVATIVE,
        primitive_problem,
        {**primitive_answer, "general": True},
    )


def test_antiderivative_rejects_malformed_and_out_of_scope_data() -> None:
    bad_problems = [
        {
            **_antiderivative_problem(),
            "coefficients": ["1", "2", "3", "4", "5", "6", "7"],
        },
        {**_antiderivative_problem(), "coefficients": ["1/0"]},
        {**_antiderivative_problem(), "coefficients": [1]},
        {**_antiderivative_problem(), "general": "yes"},
        {**_antiderivative_problem(), "unexpected": True},
        {"kind": "not_the_kind", "coefficients": ["1"], "general": False},
        {"coefficients": ["1"], "general": False},
    ]
    for problem in bad_problems:
        with pytest.raises(ValueError):
            calculus.validate_problem(ANTIDERIVATIVE, problem)

    with pytest.raises(ValueError):
        calculus.check_answer(
            ANTIDERIVATIVE,
            _antiderivative_problem(),
            {
                "kind": "polynomial_antiderivative_answer",
                "coefficients": [1],
                "general": False,
            },
        )


def test_zero_polynomial_antiderivative_is_a_constant_family() -> None:
    problem = _antiderivative_problem(["0"], general=True)
    answer = calculus.expected_answer(ANTIDERIVATIVE, problem)
    assert answer["coefficients"] == ["0"]
    assert calculus.check_answer(ANTIDERIVATIVE, problem, answer)
    for constant in ("1", "-4/7"):
        assert calculus.check_answer(
            ANTIDERIVATIVE,
            problem,
            {**answer, "coefficients": [constant]},
        )


def test_definite_integral_handles_orientation_and_equal_bounds() -> None:
    forward = _definite_problem(["1", "0", "3"], lower="0", upper="2")
    reversed_problem = _definite_problem(["1", "0", "3"], lower="2", upper="0")
    equal = _definite_problem(["1", "0", "3"], lower="2", upper="2")

    assert calculus.expected_answer(DEFINITE, forward)["value"] == "10"
    assert calculus.expected_answer(DEFINITE, reversed_problem)["value"] == "-10"
    assert calculus.expected_answer(DEFINITE, equal)["value"] == "0"

    answer = calculus.expected_answer(DEFINITE, forward)
    assert calculus.check_answer(DEFINITE, forward, answer)
    assert not calculus.check_answer(DEFINITE, forward, {**answer, "value": "9"})
    assert calculus.check_answer(
        DEFINITE,
        equal,
        {"kind": "polynomial_definite_integral_answer", "value": "0"},
    )


def test_definite_integral_is_exact_with_fractional_data() -> None:
    problem = _definite_problem(["1/3", "-1/2", "2/5"], lower="-1/2", upper="3/2")
    answer = calculus.expected_answer(DEFINITE, problem)
    # Exact rational of a small polynomial integral; never a float.
    assert Fraction(answer["value"]).denominator > 1
    assert calculus.check_answer(DEFINITE, problem, answer)

    # Every accepted bound/coefficient extreme must still produce a valid
    # closed expected answer.
    extreme = _definite_problem(
        ["10000", "-9999/997", "10000/999", "0", "-10000/991", "9999"],
        lower="-1000/999",
        upper="1000/997",
    )
    extreme_answer = calculus.expected_answer(DEFINITE, extreme)
    assert calculus.check_answer(DEFINITE, extreme, extreme_answer)

    bad_problems = [
        {**problem, "coefficients": ["1", "2", "3", "4", "5", "6", "7"]},
        {**problem, "lower": "inf"},
        {**problem, "upper": "1/0"},
        {**problem, "lower": 0},
        {**problem, "extra": 1},
    ]
    for bad in bad_problems:
        with pytest.raises(ValueError):
            calculus.validate_problem(DEFINITE, bad)


def test_first_derivative_of_supported_expression_is_independent_of_sympy_diff() -> (
    None
):
    # d/dx [sin(x) * exp(x) + log(x)] under x > 0. The expected answer is built
    # by the recursive rule engine; the checker independently verifies it.
    problem = _differentiate_problem(
        _op(
            "add",
            _op("mul", _op("sin", _sym("x")), _op("exp", _sym("x"))),
            _op("log", _sym("x")),
        )
    )
    answer = calculus.expected_answer(DIFFERENTIATE, problem)

    assert set(answer["expression"]) >= {"op"}
    assert calculus.check_answer(DIFFERENTIATE, problem, answer)
    # A known equivalent arrangement must also pass; structure may differ.
    equivalent = _differentiate_answer(
        _op(
            "add",
            _op(
                "mul",
                _op("exp", _sym("x")),
                _op("add", _op("sin", _sym("x")), _op("cos", _sym("x"))),
            ),
            _op("div", _num(1), _sym("x")),
        )
    )
    assert calculus.check_answer(DIFFERENTIATE, problem, equivalent)


def test_chain_product_and_quotient_rules_are_exact() -> None:
    chain = _differentiate_problem(_op("sin", _op("pow", _sym("x"), _num(2))))
    chain_answer = calculus.expected_answer(DIFFERENTIATE, chain)
    assert calculus.check_answer(DIFFERENTIATE, chain, chain_answer)
    equivalent_chain = _differentiate_answer(
        _op(
            "mul",
            _op("mul", _num(2), _sym("x")),
            _op("cos", _op("pow", _sym("x"), _num(2))),
        )
    )
    assert calculus.check_answer(DIFFERENTIATE, chain, equivalent_chain)

    quotient = _differentiate_problem(
        _op("div", _sym("x"), _op("exp", _sym("x"))),
        symbols=[{"name": "x", "positive": False, "nonzero": True}],
    )
    quotient_answer = calculus.expected_answer(DIFFERENTIATE, quotient)
    assert calculus.check_answer(DIFFERENTIATE, quotient, quotient_answer)


def test_differentiation_rejects_sampled_point_coincidences() -> None:
    # 2x and 2x + (x-1)^2 (x-2)^2 agree at x=1 and x=2 but differ globally.
    problem = _differentiate_problem(_op("pow", _sym("x"), _num(2)))
    fake = _differentiate_answer(
        _op(
            "add",
            _op("mul", _num(2), _sym("x")),
            _op(
                "mul",
                _op("pow", _op("sub", _sym("x"), _num(1)), _num(2)),
                _op("pow", _op("sub", _sym("x"), _num(2)), _num(2)),
            ),
        )
    )
    assert not calculus.check_answer(DIFFERENTIATE, problem, fake)


def test_differentiation_domain_and_supported_operation_boundaries() -> None:
    # log(x) needs x > 0; division needs a provably nonzero denominator.
    with pytest.raises(ValueError):
        calculus.validate_problem(
            DIFFERENTIATE,
            _differentiate_problem(
                _op("log", _sym("x")),
                symbols=[{"name": "x", "positive": False, "nonzero": False}],
            ),
        )
    with pytest.raises(ValueError):
        calculus.validate_problem(
            DIFFERENTIATE,
            _differentiate_problem(
                _op("div", _num(1), _sym("x")),
                symbols=[{"name": "x", "positive": False, "nonzero": False}],
            ),
        )
    with pytest.raises(ValueError):
        calculus.validate_problem(
            DIFFERENTIATE,
            _differentiate_problem(_op("tan", _sym("x"))),
        )
    with pytest.raises(ValueError):
        calculus.validate_problem(
            DIFFERENTIATE,
            _differentiate_problem(_op("pow", _sym("x"), _num("1/2"))),
        )

    problem = _differentiate_problem(_op("log", _sym("x")))
    # A structurally valid but unsupported candidate must fail, not pass.
    assert not calculus.check_answer(
        DIFFERENTIATE,
        problem,
        _differentiate_answer(_op("tan", _sym("x"))),
    )
    with pytest.raises(ValueError):
        calculus.check_answer(
            DIFFERENTIATE,
            problem,
            {"kind": "expression_differentiate_answer", "expression": {"bad": 1}},
        )


def test_validated_problem_preserves_candidate_ast_structure() -> None:
    expression = _op("mul", _op("sin", _sym("x")), _sym("x"))
    validated = calculus.validate_problem(
        DIFFERENTIATE, _differentiate_problem(expression)
    )
    assert validated["expression"] == expression
    answer = calculus.expected_answer(DIFFERENTIATE, validated)
    assert calculus.check_answer(DIFFERENTIATE, validated, answer)


def test_expression_literals_are_bounded_before_symbolic_work() -> None:
    huge_literal = "1" * 100
    bad_expressions = [
        _op("add", _sym("x"), _num(huge_literal)),
        _op("mul", _num("10001"), _sym("x")),
        _op("add", _sym("x"), {"param": "a"}),
        _op("mul", _sym("x"), _num("1/1001")),
    ]
    for expression in bad_expressions:
        with pytest.raises(ValueError):
            calculus.validate_problem(DIFFERENTIATE, _differentiate_problem(expression))

    problem = _differentiate_problem(_op("add", _sym("x"), _num(1)))
    assert not calculus.check_answer(
        DIFFERENTIATE,
        problem,
        _differentiate_answer(_op("add", _sym("x"), _num(huge_literal))),
    )


def test_problem_with_an_oversized_derivative_fails_before_authoring() -> None:
    product = _sym("x")
    for _ in range(20):
        product = _op("mul", product, _sym("x"))
    with pytest.raises(ValueError):
        calculus.validate_problem(DIFFERENTIATE, _differentiate_problem(product))


def test_rendered_domain_assumptions_are_explicit() -> None:
    positive = calculus.render_problem(
        DIFFERENTIATE, _differentiate_problem(_op("log", _sym("x")))
    )
    assert "positive" in positive and "nonzero" in positive

    nonzero = calculus.render_problem(
        DIFFERENTIATE,
        _differentiate_problem(
            _op("div", _num(1), _sym("x")),
            symbols=[{"name": "x", "positive": False, "nonzero": True}],
        ),
    )
    assert "nonzero" in nonzero and "positive" not in nonzero

    real = calculus.render_problem(
        DIFFERENTIATE,
        _differentiate_problem(
            _sym("x"),
            symbols=[{"name": "x", "positive": False, "nonzero": False}],
        ),
    )
    assert "real" in real


def test_wrong_answers_do_not_consult_the_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("wrong-answer construction must not call the checker")

    monkeypatch.setattr(calculus, "check_answer", fail)
    for contract_id in ALL_CONTRACTS:
        problem = calculus.boundary_problems(contract_id)[0]
        answer = calculus.expected_answer(contract_id, problem)
        assert len(calculus.wrong_answers(contract_id, problem, answer)) >= 5


@pytest.mark.parametrize("contract_id", ALL_CONTRACTS)
def test_wrong_answers_are_distinct_and_rejected(contract_id: str) -> None:
    problem = calculus.boundary_problems(contract_id)[0]
    answer = calculus.expected_answer(contract_id, problem)
    wrong = calculus.wrong_answers(contract_id, problem, answer)

    assert len(wrong) >= 5
    rendered = {repr(candidate) for candidate in wrong}
    assert len(rendered) == len(wrong)
    assert all(
        not calculus.check_answer(contract_id, problem, candidate)
        for candidate in wrong
    )


@pytest.mark.parametrize("contract_id", ALL_CONTRACTS)
def test_boundary_problems_validate_and_render(contract_id: str) -> None:
    problems = calculus.boundary_problems(contract_id)
    assert len(problems) >= 3
    for problem in problems:
        validated = calculus.validate_problem(contract_id, problem)
        answer = calculus.expected_answer(contract_id, validated)
        assert calculus.check_answer(contract_id, validated, answer)
        assert calculus.render_problem(contract_id, validated)
        assert calculus.render_answer(contract_id, answer)


@pytest.mark.parametrize("contract_id", ALL_CONTRACTS)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_problem_strategies_generate_executable_cases(
    contract_id: str, data: st.DataObject
) -> None:
    strategy = calculus.problem_strategy(contract_id)
    for _ in range(5):
        problem = data.draw(strategy)
        validated = calculus.validate_problem(contract_id, problem)
        answer = calculus.expected_answer(contract_id, validated)
        assert calculus.check_answer(contract_id, validated, answer)
        assert len(calculus.wrong_answers(contract_id, validated, answer)) >= 5


def test_unknown_contract_and_unsupported_operation_fail_safely() -> None:
    with pytest.raises(ValueError):
        calculus.validate_problem("polynomial.nope/1", {})
    with pytest.raises(ValueError):
        calculus.expected_answer("polynomial.nope/1", {})
    with pytest.raises(ValueError):
        calculus.problem_strategy("polynomial.nope/1")
    with pytest.raises(ValueError):
        calculus.boundary_problems("polynomial.nope/1")
