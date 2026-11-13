"""Adapter tests: IR goals and recipes map onto engine requests or honest gaps."""

from __future__ import annotations

from fractions import Fraction

import pytest

from edcraft_validator.domains.math.engine_adapter import (
    AdapterGap,
    grade,
    to_correctness_request,
)
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
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


def power(base: Expr, exponent: int) -> Expr:
    return Expr(op="pow", args=[base, num(exponent)])


def item(
    goal: Goal,
    *givens: Given,
    symbols: tuple[str, ...] = ("x",),
) -> MathItemSpec:
    return MathItemSpec(
        topic="test.adapter",
        symbols=[SymbolSpec(name=name) for name in symbols],
        givens=list(givens) or [Given(id="g0", kind="dataset", values=["0"])],
        goal=goal,
        text=TextSpec(mode="symbolic", template="Test item."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="expression_equiv")]),
    )


DETERMINANT_MATRIX = [[num(1), num(2)], [num(3), num(4)]]  # det = 1*4 - 2*3 = -2
LINEAR_RELATION = Relation(
    kind="eq", lhs=add(mul(num(2), sym("x")), num(3)), rhs=num(11)
)


def solve_item() -> MathItemSpec:
    return item(
        Goal(kind="solve", symbol="x"),
        Given(id="g1", relation=LINEAR_RELATION),
    )


def system_item() -> MathItemSpec:
    return item(
        Goal(kind="solve", symbols=["x", "y"]),
        Given(
            id="g1",
            relation=Relation(kind="eq", lhs=add(sym("x"), sym("y")), rhs=num(5)),
        ),
        Given(
            id="g2",
            relation=Relation(kind="eq", lhs=sub(sym("x"), sym("y")), rhs=num(1)),
        ),
        symbols=("x", "y"),
    )


# ---------------------------------------------------------------------------
# Request mapping


@pytest.mark.parametrize("kind", ["evaluate", "simplify", "expand", "factor"])
def test_scalar_goals_map_to_the_same_operation(kind: str) -> None:
    goal = Goal(kind=kind, expr=power(sym("x"), 2))
    request = to_correctness_request(
        item(goal),
        AnswerRecipe(kind="expression", items=[power(sym("x"), 2)]),
    )
    assert request.problem.operation == kind
    assert request.problem.expression == goal.expr
    assert [symbol.name for symbol in request.problem.symbols] == ["x"]


def test_derivative_maps_to_differentiate() -> None:
    goal = Goal(kind="derivative", expr=power(sym("x"), 3), symbol="x", order=2)
    request = to_correctness_request(
        item(goal),
        AnswerRecipe(kind="expression", items=[mul(num(6), sym("x"))]),
    )
    assert request.problem.operation == "differentiate"
    assert request.problem.variable == "x"
    assert request.problem.order == 2
    assert request.problem.expression == goal.expr


def test_integral_maps_to_antiderivative() -> None:
    goal = Goal(kind="integral", expr=power(sym("x"), 2), symbol="x")
    request = to_correctness_request(
        item(goal),
        AnswerRecipe(kind="expression", items=[power(sym("x"), 3)]),
    )
    assert request.problem.operation == "antiderivative"
    assert request.problem.variable == "x"


def test_solve_maps_relations_targets_and_domain() -> None:
    goal = Goal(kind="solve", symbol="x", domain="integer")
    request = to_correctness_request(
        item(goal, Given(id="g1", relation=LINEAR_RELATION)),
        AnswerRecipe(kind="set", items=[num(4)]),
    )
    assert request.problem.operation == "solve"
    assert request.problem.relations == [LINEAR_RELATION]
    assert request.problem.solve_for == ["x"]
    assert request.problem.domain == "integer"


def test_solve_with_multiple_symbols_solves_for_all() -> None:
    request = to_correctness_request(
        system_item(),
        AnswerRecipe(kind="tuple", items=[num(3), num(2)]),
    )
    assert request.problem.solve_for == ["x", "y"]
    assert len(request.problem.relations) == 2


def test_determinant_maps_matrix_and_drops_declared_symbols() -> None:
    goal = Goal(kind="determinant", matrix=DETERMINANT_MATRIX)
    request = to_correctness_request(
        item(goal, symbols=("m",)),
        AnswerRecipe(kind="numeric", items=[num(-2)]),
    )
    assert request.problem.operation == "determinant"
    assert request.problem.matrix == DETERMINANT_MATRIX
    # The engine only grades matrix operations on exact numeric entries, so the
    # unused declared dataset symbol must not reach the problem.
    assert request.problem.symbols == []


# ---------------------------------------------------------------------------
# Honest gaps


@pytest.mark.parametrize(
    ("goal", "symbols"),
    [
        (Goal(kind="limit", expr=sym("x"), point=num(0)), ("x",)),
        (Goal(kind="eigenvalues", matrix=DETERMINANT_MATRIX), ("m",)),
    ],
)
def test_unmapped_goals_raise_adapter_gap(goal: Goal, symbols: tuple[str, ...]) -> None:
    with pytest.raises(AdapterGap, match="no engine operation"):
        to_correctness_request(
            item(goal, symbols=symbols),
            AnswerRecipe(kind="numeric", items=[num(1)]),
        )


def test_interval_answer_raises_adapter_gap() -> None:
    recipe = AnswerRecipe(
        kind="interval",
        interval=RecipeInterval(lower=num(0), upper=num(1)),
    )
    with pytest.raises(AdapterGap, match="interval"):
        to_correctness_request(
            item(Goal(kind="evaluate", expr=add(num(2), num(3)))), recipe
        )


def test_boolean_answer_raises_adapter_gap() -> None:
    recipe = AnswerRecipe(kind="boolean", boolean=True)
    with pytest.raises(AdapterGap, match="boolean"):
        grade(item(Goal(kind="evaluate", expr=add(num(2), num(3)))), recipe)


def test_unbound_parameter_raises_adapter_gap() -> None:
    goal = Goal(kind="evaluate", expr=add(Expr(param="a"), num(1)))
    with pytest.raises(AdapterGap, match="unbound parameter 'a'"):
        to_correctness_request(item(goal), AnswerRecipe(kind="numeric", items=[num(6)]))


def test_unknown_symbol_raises_adapter_gap() -> None:
    goal = Goal(kind="evaluate", expr=sym("q"))
    with pytest.raises(AdapterGap, match="unknown symbol 'q'"):
        to_correctness_request(item(goal), AnswerRecipe(kind="numeric", items=[num(5)]))


# ---------------------------------------------------------------------------
# Parameter binding


def test_parameters_are_bound_into_concrete_requests() -> None:
    goal = Goal(kind="evaluate", expr=add(Expr(param="a"), num(1)))
    request = to_correctness_request(
        item(goal),
        AnswerRecipe(kind="numeric", items=[num(6)]),
        {"a": Fraction(5)},
    )
    assert request.problem.expression == add(num("5"), num(1))
    assert (
        grade(
            item(goal), AnswerRecipe(kind="numeric", items=[num(6)]), {"a": Fraction(5)}
        ).outcome
        == "correct"
    )


# ---------------------------------------------------------------------------
# End-to-end grading


def test_grade_determinant_correct_and_incorrect() -> None:
    spec = item(Goal(kind="determinant", matrix=DETERMINANT_MATRIX), symbols=("m",))
    assert grade(spec, AnswerRecipe(kind="numeric", items=[num(-2)])).outcome == (
        "correct"
    )
    assert grade(spec, AnswerRecipe(kind="numeric", items=[num(3)])).outcome == (
        "incorrect"
    )


def test_grade_solve_accepts_set_answer() -> None:
    assert grade(solve_item(), AnswerRecipe(kind="set", items=[num(4)])).outcome == (
        "correct"
    )
    assert grade(solve_item(), AnswerRecipe(kind="set", items=[num(5)])).outcome == (
        "incorrect"
    )


def test_grade_linear_system_accepts_tuple_answer() -> None:
    spec = system_item()
    assert (
        grade(spec, AnswerRecipe(kind="tuple", items=[num(3), num(2)])).outcome
        == "correct"
    )
    assert (
        grade(spec, AnswerRecipe(kind="tuple", items=[num(3), num(3)])).outcome
        == "incorrect"
    )


def test_grade_derivative_correct_and_incorrect() -> None:
    spec = item(Goal(kind="derivative", expr=power(sym("x"), 3), symbol="x"))
    correct = AnswerRecipe(kind="expression", items=[mul(num(3), power(sym("x"), 2))])
    assert grade(spec, correct).outcome == "correct"
    wrong = AnswerRecipe(kind="expression", items=[power(sym("x"), 2)])
    assert grade(spec, wrong).outcome == "incorrect"


def test_grade_expand_and_factor_goals_via_equivalence() -> None:
    expand = item(Goal(kind="expand", expr=power(add(sym("x"), num(1)), 2)))
    expanded = AnswerRecipe(
        kind="expression",
        items=[add(power(sym("x"), 2), add(mul(num(2), sym("x")), num(1)))],
    )
    assert grade(expand, expanded).outcome == "correct"
    factor = item(Goal(kind="factor", expr=sub(power(sym("x"), 2), num(1))))
    factored = AnswerRecipe(
        kind="expression",
        items=[mul(sub(sym("x"), num(1)), add(sym("x"), num(1)))],
    )
    assert grade(factor, factored).outcome == "correct"


def test_grade_distractor_kinds() -> None:
    assert (
        grade(
            solve_item(),
            Distractor(value=num(5), misconception="adds before dividing"),
        ).outcome
        == "incorrect"
    )
    assert (
        grade(
            solve_item(),
            Distractor(items=[num(4), num(5)], misconception="invents a root"),
        ).outcome
        == "incorrect"
    )
    assert (
        grade(
            system_item(),
            Distractor(components=[num(3), num(3)], misconception="copies x into y"),
        ).outcome
        == "incorrect"
    )
