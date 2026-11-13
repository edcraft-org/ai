"""Focused tests for the deterministic scalar expression handler.

The handler is deliberately conservative: accepted answers must be exactly
equivalent on the problem's natural real domain, and candidates may not
introduce extra holes or miss part of that domain.
"""

from __future__ import annotations

import pytest

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    MathAnswer,
    MathProblem,
)
from edcraft_validator.domains.math.engine.scalar import check_scalar
from edcraft_validator.domains.math.ir.schema import Expr, Relation, SymbolSpec


def num(value: object) -> Expr:
    return Expr(num=str(value))


def sym(name: str) -> Expr:
    return Expr(sym=name)


def add(*args: Expr) -> Expr:
    return Expr(op="add", args=list(args))


def mul(*args: Expr) -> Expr:
    return Expr(op="mul", args=list(args))


def sub(left: Expr, right: Expr) -> Expr:
    return Expr(op="sub", args=[left, right])


def power(base: Expr, exponent: object) -> Expr:
    return Expr(op="pow", args=[base, num(exponent)])


def _binary(op: str, left: Expr, right: Expr) -> Expr:
    return Expr(op=op, args=[left, right])


def quotient(left: Expr, right: Expr) -> Expr:
    return _binary("div", left, right)


def sqrt(value: Expr) -> Expr:
    return Expr(op="sqrt", args=[value])


def log(value: Expr) -> Expr:
    return Expr(op="log", args=[value])


def absolute(value: Expr) -> Expr:
    return Expr(op="abs", args=[value])


def sin(value: Expr) -> Expr:
    return Expr(op="sin", args=[value])


def cos(value: Expr) -> Expr:
    return Expr(op="cos", args=[value])


X = SymbolSpec(name="x")
Y = SymbolSpec(name="y")
C = SymbolSpec(name="C")


def _outcome(
    operation: str,
    expression: Expr,
    answer: Expr,
    *,
    variable: str | None = None,
    symbols: list[SymbolSpec] | None = None,
    relations: list[Relation] | None = None,
    lower: Expr | None = None,
    upper: Expr | None = None,
    order: int = 1,
    answer_kind: str = "expression",
) -> str:
    problem = MathProblem(
        operation=operation,
        expression=expression,
        variable=variable,
        symbols=symbols if symbols is not None else [X],
        relations=relations or [],
        lower=lower,
        upper=upper,
        order=order,
    )
    answer_model = (
        MathAnswer(kind="expression", expression=answer)
        if answer_kind == "expression"
        else MathAnswer(kind=answer_kind, items=[answer])
    )
    request = CorrectnessRequest(problem=problem, answer=answer_model)
    return check_scalar(EngineContext.create(request)).outcome


def _eq(name: str, value: object) -> Relation:
    return Relation(kind="eq", lhs=sym(name), rhs=num(value))


def _ne(name: str, value: object) -> Relation:
    return Relation(kind="ne", lhs=sym(name), rhs=num(value))


def test_evaluate_accepts_equivalent_algebra() -> None:
    source = add(mul(num(2), sym("x")), mul(num(3), sym("x")))
    assert _outcome("evaluate", source, mul(num(5), sym("x"))) == "correct"


def test_evaluate_keeps_exact_rational_precision() -> None:
    source = quotient(num(1), num(10**13))
    assert _outcome("evaluate", source, num("0.0000000000001")) == "correct"
    assert _outcome("evaluate", source, num("0.0000000000002")) == "incorrect"


def test_source_cancellation_keeps_its_original_hole() -> None:
    assert _outcome("simplify", quotient(sym("x"), sym("x")), num(1)) == "correct"


def test_candidate_cancellation_cannot_add_a_hole() -> None:
    assert _outcome("simplify", num(1), quotient(sym("x"), sym("x"))) == "incorrect"


def test_nested_cancelled_denominator_keeps_every_hole() -> None:
    inner = quotient(sym("x"), sym("x"))
    assert _outcome("simplify", quotient(inner, inner), num(1)) == "correct"
    assert _outcome("simplify", num(1), quotient(inner, inner)) == "incorrect"


def test_nested_rational_cancellation_in_both_directions() -> None:
    source = quotient(sub(power(sym("x"), 2), num(1)), sub(sym("x"), num(1)))
    answer = add(sym("x"), num(1))
    assert _outcome("simplify", source, answer) == "correct"
    assert _outcome("simplify", answer, source) == "incorrect"


def test_sqrt_branch_requires_absolute_value() -> None:
    source = sqrt(power(sym("x"), 2))
    assert _outcome("simplify", source, sym("x")) == "incorrect"
    assert _outcome("simplify", source, absolute(sym("x"))) == "correct"


def test_candidate_may_be_defined_beyond_a_restricted_source_domain() -> None:
    source = mul(sqrt(sym("x")), sqrt(sym("x")))
    assert _outcome("simplify", source, sym("x")) == "correct"


def test_log_domains_are_not_widened_in_either_direction() -> None:
    squared = log(power(sym("x"), 2))
    split = mul(num(2), log(sym("x")))
    assert _outcome("simplify", squared, split) == "incorrect"
    assert _outcome("simplify", split, squared) == "correct"


def test_multivariable_log_domains() -> None:
    source = add(log(sym("x")), log(sym("y")))
    answer = log(mul(sym("x"), sym("y")))
    assert _outcome("simplify", source, answer, symbols=[X, Y]) == "correct"
    assert _outcome("simplify", answer, source, symbols=[X, Y]) == "incorrect"


def test_form_operations_accept_equivalent_algebra() -> None:
    expanded = add(power(sym("x"), 2), mul(num(2), sym("x")), num(1))
    factored = power(add(sym("x"), num(1)), 2)
    assert _outcome("expand", factored, expanded) == "correct"
    assert _outcome("factor", expanded, factored) == "correct"
    assert _outcome("complete-square", expanded, factored) == "correct"


def test_differentiate_product_and_chain_rules() -> None:
    product = mul(sym("x"), sin(sym("x")))
    product_answer = add(sin(sym("x")), mul(sym("x"), cos(sym("x"))))
    assert _outcome("differentiate", product, product_answer, variable="x") == "correct"
    chain = sin(power(sym("x"), 2))
    chain_answer = mul(num(2), sym("x"), cos(power(sym("x"), 2)))
    assert _outcome("differentiate", chain, chain_answer, variable="x") == "correct"
    assert _outcome("differentiate", chain, cos(power(sym("x"), 2)), variable="x") == (
        "incorrect"
    )


def test_differentiate_higher_order() -> None:
    source = power(sym("x"), 3)
    assert (
        _outcome("differentiate", source, mul(num(6), sym("x")), variable="x", order=2)
        == "correct"
    )


def test_derivative_candidate_may_not_add_a_singularity() -> None:
    assert _outcome("differentiate", sym("x"), num(1), variable="x") == "correct"
    assert (
        _outcome("differentiate", sym("x"), quotient(sym("x"), sym("x")), variable="x")
        == "incorrect"
    )


def test_derivative_domain_of_square_root() -> None:
    source = sqrt(sym("x"))
    answer = quotient(num(1), mul(num(2), sqrt(sym("x"))))
    assert _outcome("differentiate", source, answer, variable="x") == "correct"
    wrong = quotient(num(1), mul(num(2), sym("x")))
    assert _outcome("differentiate", source, wrong, variable="x") == "incorrect"


def test_antiderivative_accepts_any_additive_constant() -> None:
    source = mul(num(2), sym("x"))
    square = power(sym("x"), 2)
    assert _outcome("antiderivative", source, square, variable="x") == "correct"
    assert (
        _outcome("antiderivative", source, add(square, num(5)), variable="x")
        == "correct"
    )
    assert (
        _outcome(
            "antiderivative",
            source,
            add(square, sym("C")),
            variable="x",
            symbols=[X, C],
        )
        == "correct"
    )
    assert (
        _outcome(
            "antiderivative",
            source,
            add(square, mul(sym("x"), sym("C"))),
            variable="x",
            symbols=[X, C],
        )
        == "incorrect"
    )


def test_antiderivative_must_cover_the_source_domain() -> None:
    source = quotient(num(1), sym("x"))
    assert (
        _outcome("antiderivative", source, log(absolute(sym("x"))), variable="x")
        == "correct"
    )
    assert _outcome("antiderivative", source, log(sym("x")), variable="x") == (
        "incorrect"
    )


def test_definite_integral_uses_exact_endpoints() -> None:
    source = power(sym("x"), 2)
    assert (
        _outcome(
            "definite-integral",
            source,
            quotient(num(1), num(3)),
            variable="x",
            lower=num(0),
            upper=num(1),
        )
        == "correct"
    )
    assert (
        _outcome(
            "definite-integral",
            source,
            quotient(num(1), num(4)),
            variable="x",
            lower=num(0),
            upper=num(1),
        )
        == "incorrect"
    )


def test_definite_integral_rejects_interior_singularity() -> None:
    assert (
        _outcome(
            "definite-integral",
            quotient(num(1), sym("x")),
            num(0),
            variable="x",
            lower=num(-1),
            upper=num(1),
        )
        == "unknown"
    )


def test_definite_integral_requires_constant_endpoints() -> None:
    assert (
        _outcome(
            "definite-integral",
            power(sym("x"), 2),
            quotient(num(1), num(3)),
            variable="x",
            lower=sym("x"),
            upper=num(1),
        )
        == "unsupported"
    )


def test_non_expression_answers_are_outside_scope() -> None:
    assert (
        _outcome(
            "simplify",
            add(sym("x"), num(1)),
            num(0),
            answer_kind="set",
        )
        == "unsupported"
    )


def test_multivariable_cancellation() -> None:
    source = quotient(mul(sym("x"), sym("y")), sym("x"))
    assert _outcome("simplify", source, sym("y"), symbols=[X, Y]) == "correct"
    assert _outcome("simplify", sym("y"), source, symbols=[X, Y]) == "incorrect"


def test_given_relation_is_used_not_ignored() -> None:
    assert _outcome("simplify", sym("x"), num(2), relations=[_eq("x", 2)]) == (
        "correct"
    )
    assert _outcome("simplify", sym("x"), num(3), relations=[_eq("x", 2)]) == (
        "incorrect"
    )


def test_given_relation_can_exclude_a_candidate_hole() -> None:
    assert (
        _outcome(
            "simplify",
            num(1),
            quotient(sym("x"), sym("x")),
            relations=[_ne("x", 0)],
        )
        == "correct"
    )


def test_given_relation_exposing_a_hole_is_not_ignored() -> None:
    assert (
        _outcome(
            "simplify",
            num(1),
            quotient(sym("x"), sym("x")),
            relations=[_eq("x", 0)],
        )
        == "incorrect"
    )


def test_equation_on_calculus_variable_is_unsupported() -> None:
    with pytest.raises(Exception) as raised:
        _outcome(
            "differentiate",
            sym("x"),
            num(1),
            variable="x",
            relations=[_eq("x", 0)],
        )
    assert raised.type.__name__ in {"EngineUnsupported", "EngineUnknown"}
