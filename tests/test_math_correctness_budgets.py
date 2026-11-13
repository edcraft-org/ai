"""Term-growth budgets and the post-computation expansion defence."""

from __future__ import annotations

import time

import pytest
import sympy

from edcraft_validator.application import math_correctness
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    EngineUnsupported,
)
from edcraft_validator.domains.math.engine.scalar import _require_bounded_expansion
from edcraft_validator.domains.math.engine.validation import (
    MAX_OUTPUT_TERMS,
    estimated_terms,
    validate_request,
)
from edcraft_validator.domains.math.ir.schema import Expr

SYMBOLS = [chr(ord("a") + index) for index in range(8)]


def _num(value: int | str) -> Expr:
    return Expr(num=str(value))


def _sym(name: str) -> Expr:
    return Expr(sym=name)


def _op(name: str, *args: Expr) -> Expr:
    return Expr(op=name, args=list(args))


def _sum() -> Expr:
    return _op("add", *[_sym(name) for name in SYMBOLS])


def _request(problem_expression: Expr, answer_expression: Expr) -> CorrectnessRequest:
    return CorrectnessRequest.model_validate(
        {
            "problem": {
                "operation": "expand",
                "symbols": [{"name": name} for name in SYMBOLS],
                "expression": problem_expression,
            },
            "answer": {"expression": answer_expression},
        }
    )


def test_eight_symbol_product_is_rejected_before_the_worker_starts(monkeypatch):
    problem = _op("mul", _op("pow", _sum(), _num(12)), _op("pow", _sum(), _num(12)))
    answer = _op("mul", _op("pow", _sum(), _num(12)), _op("pow", _sum(), _num(12)))

    def forbidden_worker(*args, **kwargs):
        raise AssertionError("the symbolic worker must not start")

    monkeypatch.setattr(math_correctness, "run_json_worker", forbidden_worker)
    result = math_correctness.check_math_correctness(_request(problem, answer))
    assert result.outcome == "unsupported"
    assert "20" in result.reason and "term" in result.reason

    with pytest.raises(EngineUnsupported):
        validate_request(_request(problem, answer))


def test_legitimate_twenty_term_expansion_still_passes():
    source = _op("pow", _op("add", _sym("a"), _sym("b"), _sym("c"), _sym("d")), _num(3))
    assert estimated_terms(source) == 20

    result = math_correctness.check_math_correctness(_request(source, source))
    assert result.outcome == "correct", result.reason


def test_estimator_matches_the_documented_rules():
    assert estimated_terms(_num(3)) == 1
    assert estimated_terms(_sym("a")) == 1
    assert estimated_terms(_op("add", _sym("a"), _sym("b"), _sym("c"))) == 3
    assert estimated_terms(_op("mul", _sum(), _sum())) == 64
    assert estimated_terms(_op("pow", _sum(), _num(12))) > MAX_OUTPUT_TERMS
    assert estimated_terms(_op("pow", _sym("a"), _num(12))) == 1
    assert estimated_terms(_op("pow", _sym("a"), _num(0))) == 1
    assert estimated_terms(_op("div", _sum(), _op("add", _sym("a"), _sym("b")))) == 10
    assert estimated_terms(_op("sin", _sum())) == 8
    # C(3 + 4 - 1, 4 - 1) = C(6, 3) = 20
    quartic = _op("pow", _op("add", *[_sym(name) for name in "abcd"]), _num(3))
    assert estimated_terms(quartic) == 20


def test_estimator_is_monotone_on_nested_growth():
    base = _op("add", *[_sym(name) for name in SYMBOLS])
    child = _op("mul", _op("pow", base, _num(2)), base)
    parent = _op("mul", child, child)
    assert estimated_terms(child) >= estimated_terms(base)
    assert estimated_terms(parent) >= estimated_terms(child)


def test_estimator_clamps_quickly_on_adversarial_trees():
    product = _sum()
    for _ in range(100):
        product = _op("mul", product, _op("pow", _sum(), _num(12)))

    started = time.perf_counter()
    assert estimated_terms(product) == MAX_OUTPUT_TERMS + 1
    assert time.perf_counter() - started < 0.25

    deeply_nested: Expr = _sym("a")
    for _ in range(1000):
        deeply_nested = _op("sin", deeply_nested)
    started = time.perf_counter()
    assert estimated_terms(deeply_nested) == 1
    assert time.perf_counter() - started < 0.25


def test_scalar_defence_refuses_oversized_expanded_candidate():
    symbols = [sympy.Symbol(f"t{index}") for index in range(MAX_OUTPUT_TERMS + 1)]
    widened = sympy.Add(*symbols)
    with pytest.raises(EngineUnsupported):
        _require_bounded_expansion(widened, "answer expression")
    _require_bounded_expansion(sympy.expand((sympy.Symbol("x") + 1) ** 2), "ok")


def test_negative_integer_power_is_bounded_by_its_magnitude():
    # (a+...+h)^-12 grows like the positive power in numerator and denominator;
    # it must be refused at validation instead of reaching the worker.
    request = {
        "problem": {
            "operation": "simplify",
            "symbols": [{"name": name} for name in "abcdefgh"],
            "expression": _op("pow", _sum(), _num(-12)),
        },
        "answer": {"expression": _num(1)},
    }
    with pytest.raises(EngineUnsupported):
        validate_request(CorrectnessRequest.model_validate(request))
    assert estimated_terms(_op("pow", _sum(), _num(-2))) < MAX_OUTPUT_TERMS
