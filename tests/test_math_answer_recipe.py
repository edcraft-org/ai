"""AnswerRecipe schema validation, compilation and parameter substitution."""

from __future__ import annotations

from fractions import Fraction

import pytest
import sympy
from pydantic import ValidationError

from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.instantiate import substitute_item
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    RecipeInterval,
    Relation,
    SymbolSpec,
    TextSpec,
    item_parameters,
)
from edcraft_validator.domains.math.validation.answers import compile_answer_recipe


def num(value: int | str) -> Expr:
    return Expr(num=str(value))


def sym(name: str) -> Expr:
    return Expr(sym=name)


def param(name: str) -> Expr:
    return Expr(param=name)


def add(*args: Expr) -> Expr:
    return Expr(op="add", args=list(args))


def mul(*args: Expr) -> Expr:
    return Expr(op="mul", args=list(args))


def sub(left: Expr, right: Expr) -> Expr:
    return Expr(op="sub", args=[left, right])


def recipe_item(recipe: AnswerRecipe | None) -> MathItemSpec:
    return MathItemSpec(
        topic="school.linear_equation",
        symbols=[SymbolSpec(name="x")],
        givens=[
            Given(
                id="g1",
                relation=Relation(
                    kind="eq",
                    lhs=add(mul(num(2), sym("x")), num(3)),
                    rhs=num(11),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        answer_recipe=recipe,
        text=TextSpec(mode="symbolic", template="Solve 2x + 3 = 11."),
    )


def expr_has_param(expr: Expr) -> bool:
    if expr.param is not None:
        return True
    return any(expr_has_param(child) for child in expr.args)


def recipe_has_param(recipe: AnswerRecipe) -> bool:
    checks = [expr_has_param(entry) for entry in recipe.items]
    if recipe.interval is not None:
        for endpoint in (recipe.interval.lower, recipe.interval.upper):
            if endpoint is not None:
                checks.append(expr_has_param(endpoint))
    for row in recipe.matrix or []:
        checks.extend(expr_has_param(cell) for cell in row)
    return any(checks)


def test_compile_scalar_recipes_without_params() -> None:
    symbols = [SymbolSpec(name="x")]
    x = sympy.Symbol("x", real=True)

    assert compile_answer_recipe(
        AnswerRecipe(kind="numeric", items=[num("7/2")]), symbols
    ) == sympy.Rational(7, 2)
    assert (
        compile_answer_recipe(
            AnswerRecipe(kind="expression", items=[add(mul(num(2), sym("x")), num(1))]),
            symbols,
        )
        == 2 * x + 1
    )
    assert compile_answer_recipe(
        AnswerRecipe(kind="set", items=[num(3), num(1), num(2)]), symbols
    ) == sympy.FiniteSet(1, 2, 3)
    assert compile_answer_recipe(
        AnswerRecipe(kind="tuple", items=[num(1), num(2)]), symbols
    ) == sympy.Tuple(1, 2)
    assert compile_answer_recipe(
        AnswerRecipe(kind="matrix", matrix=[[num(1), num(0)], [num(0), num(1)]]),
        symbols,
    ) == sympy.Matrix([[1, 0], [0, 1]])


def test_compile_recipes_with_params() -> None:
    symbols: list[SymbolSpec] = []
    params = {"p": Fraction(1, 2), "q": Fraction(-3), "r": Fraction(4)}

    assert compile_answer_recipe(
        AnswerRecipe(kind="numeric", items=[add(param("p"), num(1))]),
        symbols,
        params,
    ) == sympy.Rational(3, 2)
    assert compile_answer_recipe(
        AnswerRecipe(kind="expression", items=[mul(num(2), param("q"))]),
        symbols,
        params,
    ) == sympy.Integer(-6)
    assert compile_answer_recipe(
        AnswerRecipe(
            kind="set", items=[add(param("p"), num(1)), mul(num(2), param("q"))]
        ),
        symbols,
        params,
    ) == sympy.FiniteSet(sympy.Rational(3, 2), sympy.Integer(-6))
    assert compile_answer_recipe(
        AnswerRecipe(kind="tuple", items=[param("p"), sub(param("q"), num(1))]),
        symbols,
        params,
    ) == sympy.Tuple(sympy.Rational(1, 2), sympy.Integer(-4))
    assert compile_answer_recipe(
        AnswerRecipe(
            kind="matrix",
            matrix=[[param("p"), param("q")], [param("r"), num(0)]],
        ),
        symbols,
        params,
    ) == sympy.Matrix(
        [
            [sympy.Rational(1, 2), sympy.Integer(-3)],
            [sympy.Integer(4), sympy.Integer(0)],
        ]
    )
    assert (
        compile_answer_recipe(AnswerRecipe(kind="boolean", boolean=True), symbols)
        is sympy.true
    )
    assert (
        compile_answer_recipe(AnswerRecipe(kind="boolean", boolean=False), symbols)
        is sympy.false
    )


def test_compile_interval_recipes_open_closed_and_unbounded() -> None:
    symbols: list[SymbolSpec] = []

    closed = AnswerRecipe(
        kind="interval",
        interval=RecipeInterval(
            lower=num(0), upper=num(1), lower_open=False, upper_open=False
        ),
    )
    assert compile_answer_recipe(closed, symbols) == sympy.Interval(0, 1, False, False)

    open_recipe = AnswerRecipe(
        kind="interval",
        interval=RecipeInterval(lower=num(0), upper=num(1)),
    )
    assert compile_answer_recipe(open_recipe, symbols) == sympy.Interval(
        0, 1, True, True
    )

    half_open = AnswerRecipe(
        kind="interval",
        interval=RecipeInterval(
            lower=param("lo"), upper=num(2), lower_open=False, upper_open=True
        ),
    )
    assert compile_answer_recipe(
        half_open, symbols, {"lo": Fraction(1, 3)}
    ) == sympy.Interval(sympy.Rational(1, 3), sympy.Integer(2), False, True)

    below = AnswerRecipe(
        kind="interval",
        interval=RecipeInterval(upper=num(2), upper_open=False),
    )
    assert compile_answer_recipe(below, symbols) == sympy.Interval(
        sympy.S.NegativeInfinity, sympy.Integer(2), True, False
    )

    above = AnswerRecipe(
        kind="interval",
        interval=RecipeInterval(lower=num(0)),
    )
    assert compile_answer_recipe(above, symbols) == sympy.Interval(
        sympy.Integer(0), sympy.S.Infinity, True, True
    )

    unbounded = AnswerRecipe(kind="interval", interval=RecipeInterval())
    assert compile_answer_recipe(unbounded, symbols) == sympy.Interval(
        sympy.S.NegativeInfinity, sympy.S.Infinity, True, True
    )


def test_compile_recipe_reports_errors_with_context() -> None:
    with pytest.raises(MathCompileError, match="invalid expression answer recipe"):
        compile_answer_recipe(
            AnswerRecipe(kind="expression", items=[sym("y")]),
            [SymbolSpec(name="x")],
        )
    with pytest.raises(MathCompileError, match="unbound parameter 'p'"):
        compile_answer_recipe(
            AnswerRecipe(kind="numeric", items=[param("p")]),
            [SymbolSpec(name="x")],
        )


def test_recipe_validator_rejects_cross_kind_fields() -> None:
    with pytest.raises(ValidationError, match="must not set"):
        AnswerRecipe(kind="numeric", items=[num(1)], boolean=True)
    with pytest.raises(ValidationError, match="must not set"):
        AnswerRecipe(kind="set", items=[num(1)], interval=RecipeInterval(lower=num(0)))
    with pytest.raises(ValidationError, match="must not set"):
        AnswerRecipe(kind="interval", interval=RecipeInterval(), matrix=[[num(1)]])
    with pytest.raises(ValidationError, match="must not set"):
        AnswerRecipe(kind="matrix", matrix=[[num(1)]], items=[num(2)])
    with pytest.raises(ValidationError, match="must not set"):
        AnswerRecipe(kind="boolean", boolean=True, items=[num(1)])


def test_recipe_validator_rejects_empty_and_multi_item_kinds() -> None:
    with pytest.raises(ValidationError, match="exactly one item"):
        AnswerRecipe(kind="numeric")
    with pytest.raises(ValidationError, match="exactly one item"):
        AnswerRecipe(kind="expression", items=[num(1), num(2)])
    with pytest.raises(ValidationError, match="at least one item"):
        AnswerRecipe(kind="set", items=[])
    with pytest.raises(ValidationError, match="at least one item"):
        AnswerRecipe(kind="tuple", items=[])


def test_item_parameters_include_recipe_parameters() -> None:
    body = recipe_item(
        AnswerRecipe(
            kind="interval",
            interval=RecipeInterval(
                lower=param("lo"),
                upper=add(param("lo"), param("hi")),
                lower_open=False,
                upper_open=True,
            ),
        )
    )
    assert item_parameters(body) == {"lo", "hi"}


def test_template_accepts_declared_recipe_parameters() -> None:
    body = recipe_item(AnswerRecipe(kind="set", items=[add(param("p"), num(1))]))
    template = MathTemplateSpec(
        topic="school.linear_equation",
        parameters=[ParameterSpec(name="p", values=["1", "2"])],
        body=body,
    )
    assert item_parameters(template.body) == {"p"}


def test_template_rejects_undeclared_parameters_in_recipe() -> None:
    body = recipe_item(
        AnswerRecipe(
            kind="set",
            items=[add(param("p"), num(1)), param("secret")],
        )
    )
    with pytest.raises(ValidationError, match="undeclared parameters"):
        MathTemplateSpec(
            topic="school.linear_equation",
            parameters=[ParameterSpec(name="p", values=["1", "2"])],
            body=body,
        )


def test_substitute_item_replaces_params_in_recipe_items() -> None:
    item = recipe_item(
        AnswerRecipe(
            kind="set",
            items=[add(param("p"), num(1)), mul(num(2), param("q"))],
        )
    )
    substituted = substitute_item(item, {"p": Fraction(1, 2), "q": Fraction(3)})

    assert substituted.answer_recipe is not None
    assert substituted.answer_recipe.items == [
        add(num("1/2"), num(1)),
        mul(num(2), num(3)),
    ]
    assert not recipe_has_param(substituted.answer_recipe)
    compiled = compile_answer_recipe(substituted.answer_recipe, substituted.symbols)
    assert compiled == sympy.FiniteSet(sympy.Rational(3, 2), sympy.Integer(6))


def test_substitute_item_replaces_params_in_matrix_and_interval() -> None:
    matrix_item = recipe_item(
        AnswerRecipe(
            kind="matrix",
            matrix=[[add(param("a"), param("b")), num(1)]],
        )
    )
    substituted = substitute_item(matrix_item, {"a": Fraction(2), "b": Fraction(5)})

    assert substituted.answer_recipe is not None
    assert substituted.answer_recipe.matrix == [[add(num(2), num(5)), num(1)]]
    assert not recipe_has_param(substituted.answer_recipe)

    interval_item = recipe_item(
        AnswerRecipe(
            kind="interval",
            interval=RecipeInterval(
                lower=param("lo"),
                upper=param("hi"),
                lower_open=False,
                upper_open=True,
            ),
        )
    )
    substituted_interval = substitute_item(
        interval_item, {"lo": Fraction(-1, 2), "hi": Fraction(3)}
    )

    assert substituted_interval.answer_recipe is not None
    interval = substituted_interval.answer_recipe.interval
    assert interval is not None
    assert interval.lower == num("-1/2")
    assert interval.upper == num(3)
    assert interval.lower_open is False
    assert interval.upper_open is True
    assert not recipe_has_param(substituted_interval.answer_recipe)
    assert compile_answer_recipe(
        substituted_interval.answer_recipe, substituted_interval.symbols
    ) == sympy.Interval(sympy.Rational(-1, 2), sympy.Integer(3), False, True)


def test_substitute_item_leaves_the_recipe_display_untouched() -> None:
    item = recipe_item(AnswerRecipe(kind="numeric", items=[param("p")], display="{p}"))
    substituted = substitute_item(item, {"p": Fraction(1, 2)})

    assert substituted.answer_recipe is not None
    assert substituted.answer_recipe.items == [num("1/2")]
    assert substituted.answer_recipe.display == "{p}"
