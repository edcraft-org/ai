"""Form registry tests: the shape rules a goal demands of its answer."""

from __future__ import annotations

from fractions import Fraction

import pytest

from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    PrimitiveSpec,
    RecipeInterval,
    Relation,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.validation.forms import FormResult, check_form


def num(value: int | str) -> Expr:
    return Expr(num=str(value))


def sym(name: str) -> Expr:
    return Expr(sym=name)


def add(*args: Expr) -> Expr:
    return Expr(op="add", args=list(args))


def mul(*args: Expr) -> Expr:
    return Expr(op="mul", args=list(args))


def sub(left: Expr, right: Expr) -> Expr:
    return Expr(op="sub", args=[left, right])


def div(left: Expr, right: Expr) -> Expr:
    return Expr(op="div", args=[left, right])


def power(base: Expr, exponent: int) -> Expr:
    return Expr(op="pow", args=[base, num(exponent)])


def item(goal: Goal, *givens: Given, symbols: tuple[str, ...] = ("x",)) -> MathItemSpec:
    return MathItemSpec(
        topic="test.forms",
        symbols=[SymbolSpec(name=name) for name in symbols],
        givens=list(givens) or [Given(id="g0", kind="dataset", values=["0"])],
        goal=goal,
        text=TextSpec(mode="symbolic", template="Test item."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="expression_equiv")]),
    )


def one(expr: Expr) -> AnswerRecipe:
    return AnswerRecipe(kind="expression", items=[expr])


DETERMINANT_MATRIX = [[num(1), num(2)], [num(3), num(4)]]
LINEAR_RELATION = Relation(
    kind="eq", lhs=add(mul(num(2), sym("x")), num(3)), rhs=num(11)
)


def solve_item() -> MathItemSpec:
    return item(
        Goal(kind="solve", symbol="x"),
        Given(id="g1", relation=LINEAR_RELATION),
    )


# ---------------------------------------------------------------------------
# expand


def expand_item() -> MathItemSpec:
    return item(Goal(kind="expand", expr=power(add(sym("x"), num(1)), 2)))


def test_expand_accepts_a_fully_expanded_answer() -> None:
    result = check_form(
        expand_item(),
        one(add(power(sym("x"), 2), add(mul(num(2), sym("x")), num(1)))),
    )
    assert result == FormResult("pass")


def test_expand_rejects_a_factored_answer() -> None:
    result = check_form(expand_item(), one(power(add(sym("x"), num(1)), 2)))
    assert result.status == "fail"
    assert "expanded" in result.reason


def test_expand_rejects_a_partially_factored_answer() -> None:
    result = check_form(
        expand_item(), one(mul(power(sym("x"), 2), add(sym("x"), num(1))))
    )
    assert result.status == "fail"
    assert "expanded" in result.reason


def test_expand_rejects_a_non_polynomial_answer() -> None:
    result = check_form(expand_item(), one(div(num(1), add(sym("x"), num(1)))))
    assert result.status == "fail"
    assert "polynomial" in result.reason


def test_expand_binds_parameters_before_checking() -> None:
    result = check_form(
        expand_item(),
        one(mul(sym("x"), Expr(param="a"))),
        {"a": Fraction(2)},
    )
    assert result == FormResult("pass")


# ---------------------------------------------------------------------------
# factor


def factor_item() -> MathItemSpec:
    return item(Goal(kind="factor", expr=sub(power(sym("x"), 2), num(1))))


def test_factor_accepts_a_factored_answer() -> None:
    result = check_form(
        factor_item(), one(mul(sub(sym("x"), num(1)), add(sym("x"), num(1))))
    )
    assert result == FormResult("pass")


def test_factor_accepts_a_power_of_an_irreducible_factor() -> None:
    result = check_form(factor_item(), one(power(add(sym("x"), num(1)), 2)))
    assert result == FormResult("pass")


def test_factor_rejects_an_expanded_reducible_polynomial() -> None:
    result = check_form(factor_item(), one(sub(power(sym("x"), 2), num(1))))
    assert result.status == "fail"
    assert "factored" in result.reason


def test_factor_accepts_an_expanded_irreducible_polynomial() -> None:
    result = check_form(factor_item(), one(add(power(sym("x"), 2), num(1))))
    assert result == FormResult("pass")


def test_factor_rejects_a_non_polynomial_answer() -> None:
    result = check_form(factor_item(), one(power(add(sym("x"), num(1)), -1)))
    assert result.status == "fail"
    assert "polynomial" in result.reason


# ---------------------------------------------------------------------------
# solve


def test_solve_accepts_a_set_answer() -> None:
    result = check_form(solve_item(), AnswerRecipe(kind="set", items=[num(4)]))
    assert result == FormResult("pass")


def test_solve_accepts_a_tuple_answer() -> None:
    result = check_form(solve_item(), AnswerRecipe(kind="tuple", items=[num(4)]))
    assert result == FormResult("pass")


def test_solve_rejects_a_single_expression_answer() -> None:
    result = check_form(solve_item(), one(num(4)))
    assert result.status == "fail"
    assert "set or an ordered tuple" in result.reason


# ---------------------------------------------------------------------------
# derivative and integral


def derivative_item() -> MathItemSpec:
    return item(Goal(kind="derivative", expr=power(sym("x"), 3), symbol="x"))


def integral_item() -> MathItemSpec:
    return item(Goal(kind="integral", expr=power(sym("x"), 2), symbol="x"))


def test_derivative_accepts_a_plain_expression() -> None:
    result = check_form(derivative_item(), one(mul(num(3), power(sym("x"), 2))))
    assert result == FormResult("pass")


def test_derivative_is_unsupported_for_non_expression_answers() -> None:
    result = check_form(derivative_item(), AnswerRecipe(kind="set", items=[num(1)]))
    assert result == FormResult(
        "unsupported", "derivative form applies to expression answers only"
    )


def test_integral_accepts_a_plain_expression() -> None:
    result = check_form(integral_item(), one(div(power(sym("x"), 3), num(3))))
    assert result == FormResult("pass")


def test_integral_is_unsupported_for_non_expression_answers() -> None:
    result = check_form(integral_item(), AnswerRecipe(kind="tuple", items=[num(1)]))
    assert result.status == "unsupported"


# ---------------------------------------------------------------------------
# determinant


def determinant_item() -> MathItemSpec:
    return item(Goal(kind="determinant", matrix=DETERMINANT_MATRIX), symbols=("m",))


def test_determinant_accepts_a_finite_numeric_scalar() -> None:
    recipe = AnswerRecipe(kind="numeric", items=[num(-2)])
    result = check_form(determinant_item(), recipe)
    assert result == FormResult("pass")


def test_determinant_rejects_non_expression_answers() -> None:
    result = check_form(determinant_item(), AnswerRecipe(kind="set", items=[num(-2)]))
    assert result.status == "fail"


def test_determinant_rejects_a_non_finite_value() -> None:
    result = check_form(determinant_item(), one(div(num(1), num(0))))
    assert result.status == "fail"
    assert "finite" in result.reason


# ---------------------------------------------------------------------------
# evaluate, simplify, limit, eigenvalues


@pytest.mark.parametrize("kind", ["evaluate", "simplify"])
def test_scalar_expression_goals_accept_expression_answers(kind: str) -> None:
    spec = item(Goal(kind=kind, expr=add(num(2), num(3))))
    result = check_form(spec, AnswerRecipe(kind="numeric", items=[num(5)]))
    assert result == FormResult("pass")


def test_evaluate_rejects_non_expression_answers() -> None:
    spec = item(Goal(kind="evaluate", expr=add(num(2), num(3))))
    result = check_form(spec, AnswerRecipe(kind="set", items=[num(5)]))
    assert result.status == "fail"


def test_limit_goal_is_unsupported() -> None:
    spec = item(Goal(kind="limit", expr=sym("x"), point=num(0)))
    result = check_form(spec, one(num(1)))
    assert result.status == "unsupported"
    assert "limit" in result.reason


def test_eigenvalues_goal_is_unsupported() -> None:
    spec = item(Goal(kind="eigenvalues", matrix=DETERMINANT_MATRIX), symbols=("m",))
    result = check_form(spec, AnswerRecipe(kind="numeric", items=[num(1)]))
    assert result.status == "unsupported"
    assert "eigenvalues" in result.reason


# ---------------------------------------------------------------------------
# Answer kinds and robustness


def test_interval_answer_is_unsupported() -> None:
    spec = item(Goal(kind="evaluate", expr=add(num(2), num(3))))
    result = check_form(
        spec,
        AnswerRecipe(
            kind="interval", interval=RecipeInterval(lower=num(0), upper=num(1))
        ),
    )
    assert result.status == "unsupported"
    assert "interval" in result.reason


def test_boolean_answer_is_unsupported() -> None:
    spec = solve_item()
    result = check_form(spec, AnswerRecipe(kind="boolean", boolean=True))
    assert result.status == "unsupported"
    assert "boolean" in result.reason


def test_a_compilation_failure_fails_instead_of_raising() -> None:
    spec = item(Goal(kind="evaluate", expr=add(num(2), num(3))))
    result = check_form(spec, one(sym("q")))
    assert result.status == "fail"
    assert "does not compile" in result.reason


def test_a_matrix_answer_has_no_expression_form() -> None:
    result = check_form(expand_item(), AnswerRecipe(kind="matrix", matrix=[[num(1)]]))
    assert result.status == "fail"
