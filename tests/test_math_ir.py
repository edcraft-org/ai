"""Typed IR, recipe compilation, option distinctness, and harness tests."""

from __future__ import annotations

from fractions import Fraction

import pytest
import sympy
from pydantic import ValidationError

from edcraft_validator.domains.math.ir.compile import MathCompileError, compile_expr
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    Relation,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.domains.math.validation.answers import compile_answer_recipe
from edcraft_validator.domains.math.validation.distinct import (
    expression_equivalence,
    same_value,
)
from edcraft_validator.domains.math.validation.harness import (
    validate_item,
    validate_template,
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


def div(left: Expr, right: Expr) -> Expr:
    return Expr(op="div", args=[left, right])


def power(left: Expr, right: Expr) -> Expr:
    return Expr(op="pow", args=[left, right])


def linear_item(
    *,
    a: int = 2,
    b: int = 3,
    c: int = 11,
    answer_recipe: AnswerRecipe | None = None,
    distractors: list[Distractor] | None = None,
) -> MathItemSpec:
    """``a*x + b = c`` with the exact solution ``(c - b) / a`` as its recipe."""
    return MathItemSpec(
        topic="school.linear_equation",
        symbols=[SymbolSpec(name="x")],
        givens=[
            Given(
                id="g1",
                relation=Relation(
                    kind="eq",
                    lhs=add(mul(num(a), sym("x")), num(b)),
                    rhs=num(c),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        answer_recipe=answer_recipe
        if answer_recipe is not None
        else AnswerRecipe(
            kind="set",
            items=[div(sub(num(c), num(b)), num(a))],
        ),
        distractors=distractors or [],
        text=TextSpec(mode="symbolic", template=f"Solve {a}x + {b} = {c}."),
    )


def test_compile_rejects_unknown_operator_and_symbol() -> None:
    symbols = {"x": sympy.Symbol("x")}
    with pytest.raises(MathCompileError, match="unsupported operator"):
        compile_expr(Expr(op="eval", args=[num(1)]), symbols)
    with pytest.raises(MathCompileError, match="unknown symbol"):
        compile_expr(sym("y"), symbols)


def test_compile_rejects_unbounded_exponent_and_deep_tree() -> None:
    symbols = {"x": sympy.Symbol("x")}
    with pytest.raises(MathCompileError, match="exponents are bounded"):
        compile_expr(power(sym("x"), num(99)), symbols)
    deep = num(1)
    for _ in range(30):
        deep = add(deep, num(1))
    with pytest.raises(MathCompileError, match="too deep"):
        compile_expr(deep, symbols)


def test_answer_recipes_compile_to_values() -> None:
    assert compile_answer_recipe(
        AnswerRecipe(kind="numeric", items=[div(num(1), num(3))]), []
    ) == sympy.Rational(1, 3)

    quadratic = AnswerRecipe(
        kind="set",
        items=[
            div(add(num(6), num(2)), num(2)),
            div(sub(num(6), num(2)), num(2)),
        ],
    )
    assert compile_answer_recipe(quadratic, []) == sympy.FiniteSet(4, 2)

    assert compile_answer_recipe(
        AnswerRecipe(kind="tuple", items=[num(3), num(2)]), []
    ) == sympy.Tuple(3, 2)

    matrix = compile_answer_recipe(
        AnswerRecipe(kind="matrix", matrix=[[num(1), num(2)]]), []
    )
    assert matrix == sympy.Matrix([[1, 2]])

    with pytest.raises(ValidationError, match="exactly one item"):
        AnswerRecipe(kind="numeric", items=[num(1), num(2)])


def test_expression_equivalence_is_tri_state() -> None:
    x = sympy.Symbol("x")
    assert (
        expression_equivalence(sympy.sin(x) ** 2 + sympy.cos(x) ** 2, sympy.Integer(1))
        is True
    )
    assert expression_equivalence(x, x + 1) is False


def test_expression_equivalence_finds_a_counterexample_before_simplifying(
    monkeypatch,
) -> None:
    """A sampled mismatch settles inequality without a symbolic simplification."""
    from edcraft_validator.domains.math.validation import distinct

    original = distinct.sympy.simplify

    def guarded(value, **kwargs):
        if getattr(value, "free_symbols", None):
            raise TypeError("symbolic simplify disabled for this test")
        return original(value, **kwargs)

    x = sympy.Symbol("x")
    monkeypatch.setattr(distinct.sympy, "simplify", guarded)

    assert expression_equivalence(x, x + 1) is False


def test_same_value_compares_supported_answer_shapes() -> None:
    assert same_value(sympy.Tuple(1, 2), sympy.Tuple(1, 2))
    assert not same_value(sympy.Tuple(1, 2), sympy.Integer(1))
    assert same_value([[1, 2]], [[1, 2]])
    assert not same_value([[1, 2]], [[1, 3]])
    assert same_value(sympy.FiniteSet(1, 2), sympy.FiniteSet(2, 1))
    assert not same_value(sympy.FiniteSet(1, 2), sympy.FiniteSet(1, 3))
    assert not same_value("north", "south")
    assert same_value(sympy.Integer(2), sympy.Rational(4, 2))


def test_harness_accepts_a_correct_recipe_and_rejects_a_wrong_key() -> None:
    assert validate_item(linear_item()).report.status == "passed"

    wrong_key = validate_item(
        linear_item(answer_recipe=AnswerRecipe(kind="set", items=[num(5)]))
    )
    assert wrong_key.report.status == "failed"
    assert any(
        result.check == "engine_correctness" and result.status == "failed"
        for result in wrong_key.report.checks
    )


def test_harness_requires_an_answer_recipe() -> None:
    item = linear_item().model_copy(update={"answer_recipe": None})
    report = validate_item(item)
    assert report.report.status == "failed"
    assert any("answer_recipe" in finding for finding in report.report.findings)


def test_harness_blocks_duplicate_and_correct_distractors() -> None:
    duplicate = validate_item(
        linear_item(
            distractors=[
                Distractor(value=num(7), misconception="COPY_ONE"),
                Distractor(value=num(7), misconception="COPY_TWO"),
            ]
        )
    )
    assert duplicate.report.status == "failed"
    assert all(option.result.status == "failed" for option in duplicate.report.options)

    key_like = validate_item(
        linear_item(distractors=[Distractor(value=num(4), misconception="COPY_KEY")])
    )
    assert key_like.report.status == "failed"
    assert key_like.report.options[0].result.status == "failed"


def test_template_sweep_blocks_a_failing_variant() -> None:
    body = MathItemSpec(
        topic="school.linear_equation",
        symbols=[SymbolSpec(name="x")],
        givens=[
            Given(
                id="g1",
                relation=Relation(
                    kind="eq",
                    lhs=add(mul(Expr(param="a"), sym("x")), Expr(param="b")),
                    rhs=Expr(param="c"),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        answer_recipe=AnswerRecipe(
            kind="set",
            items=[div(sub(Expr(param="c"), Expr(param="b")), Expr(param="a"))],
        ),
        distractors=[Distractor(value=Expr(param="d"), misconception="WRONG_CONSTANT")],
        text=TextSpec(mode="symbolic", template="Solve for x."),
    )
    template = MathTemplateSpec(
        topic="school.linear_equation",
        parameters=[
            ParameterSpec(name="a", values=["2"]),
            ParameterSpec(name="b", values=["3"]),
            ParameterSpec(name="c", values=["11"]),
            ParameterSpec(name="d", values=["7", "4"]),
        ],
        body=body,
    )

    report = validate_template(template)
    assert report.report.status == "failed"
    assert report.variants_checked == 2


def test_bounded_sample_reports_property_based_coverage() -> None:
    body = MathItemSpec(
        topic="school.quadratic",
        symbols=[SymbolSpec(name="x")],
        givens=[
            Given(
                id="g1",
                relation=Relation(
                    kind="eq",
                    lhs=add(
                        sub(
                            power(sym("x"), num(2)),
                            mul(add(Expr(param="p"), Expr(param="q")), sym("x")),
                        ),
                        mul(Expr(param="p"), Expr(param="q")),
                    ),
                    rhs=num(0),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        answer_recipe=AnswerRecipe(
            kind="set", items=[Expr(param="p"), Expr(param="q")]
        ),
        text=TextSpec(mode="symbolic", template="Solve for x."),
    )
    template = MathTemplateSpec(
        topic="school.quadratic",
        parameters=[
            ParameterSpec(name="p", values=["2", "3"]),
            ParameterSpec(name="q", values=["5", "7"]),
        ],
        body=body,
    )

    report = validate_template(template, max_variants=1)

    assert report.report.status == "passed"
    assert report.checking_mode == "property_based"
    assert report.seed == 0
    assert report.variants_checked == 1
    assert report.variants_total == 4
    assert not any("truncated" in finding for finding in report.report.findings)


def test_recipe_parameters_compile_exactly() -> None:
    recipe = AnswerRecipe(kind="numeric", items=[div(Expr(param="a"), num(4))])
    assert compile_answer_recipe(
        recipe, [SymbolSpec(name="x")], {"a": Fraction(1, 2)}
    ) == sympy.Rational(1, 8)


def test_matrix_shapes_must_be_rectangular() -> None:
    with pytest.raises(ValidationError, match="rectangular"):
        AnswerRecipe(kind="matrix", matrix=[[num(1), num(2)], [num(3)]])

    with pytest.raises(ValidationError, match="rectangular"):
        MathItemSpec(
            topic="school.matrix",
            symbols=[SymbolSpec(name="x")],
            givens=[Given(id="g1", kind="domain", symbol="x", domain="real")],
            goal=Goal(
                kind="determinant",
                matrix=[[num(1), num(2)], [num(3)]],
            ),
            text=TextSpec(mode="symbolic", template="Find the determinant."),
        )
