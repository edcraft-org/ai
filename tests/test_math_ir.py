"""Typed IR, solver, primitives, harness, and linear migration tests."""

from __future__ import annotations

from fractions import Fraction

import pytest
import sympy
from math_helpers import math_candidate

from edcraft_validator.domains.math.ir.compile import MathCompileError, compile_expr
from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Distractor,
    Expr,
    Given,
    Goal,
    Interval,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    PrimitiveSpec,
    Relation,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.ir.solve import solve_item
from edcraft_validator.domains.math.linear_ir import linear_template_ir
from edcraft_validator.domains.math.validation.harness import (
    Witness,
    validate_item,
    validate_template,
)
from edcraft_validator.domains.math.validation.primitives import (
    collection_equal,
    expression_equiv,
    interval_equal,
    matrix_equal,
    numeric_equal,
    solution_set_equal,
)
from edcraft_validator.domains.math.validation.results import PrimitiveResult


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
    answer: Answer | None = None,
    distractors: list[Distractor] | None = None,
) -> MathItemSpec:
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
        answer=answer,
        distractors=distractors or [],
        text=TextSpec(mode="symbolic", template=f"Solve {a}x + {b} = {c}."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
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


def test_solve_linear_and_quadratic() -> None:
    assert solve_item(linear_item()).answer.items == ["4"]

    roots = MathItemSpec(
        topic="school.quadratic",
        symbols=[SymbolSpec(name="x")],
        givens=[
            Given(
                id="g1",
                relation=Relation(
                    kind="eq",
                    lhs=sub(power(sym("x"), num(2)), num(6)),
                    rhs=mul(num(1), sym("x")),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        text=TextSpec(mode="symbolic", template="x^2 - 6 = x"),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )
    result = solve_item(roots)
    assert result.answer.kind == "set"
    assert set(result.answer.items) == {
        sympy.sstr(sympy.Integer(-2)),
        sympy.sstr(sympy.Integer(3)),
    }


def test_solve_system_derivative_and_determinant() -> None:
    system = MathItemSpec(
        topic="school.linear_system",
        symbols=[SymbolSpec(name="x"), SymbolSpec(name="y")],
        givens=[
            Given(
                id="g1",
                relation=Relation(kind="eq", lhs=add(sym("x"), sym("y")), rhs=num(5)),
            ),
            Given(
                id="g2",
                relation=Relation(kind="eq", lhs=sub(sym("x"), sym("y")), rhs=num(1)),
            ),
        ],
        goal=Goal(kind="solve", symbols=["x", "y"]),
        text=TextSpec(mode="symbolic", template="x+y=5, x-y=1"),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )
    assert solve_item(system).answer.items == ["3", "2"]

    derivative = MathItemSpec(
        topic="university.derivative",
        symbols=[SymbolSpec(name="x")],
        givens=[Given(id="g1", kind="domain", symbol="x", domain="real")],
        goal=Goal(kind="derivative", symbol="x", expr=power(sym("x"), num(3))),
        text=TextSpec(mode="symbolic", template="Differentiate x^3."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="expression_equiv")]),
    )
    assert solve_item(derivative).answer.items == ["3*x**2"]

    determinant = MathItemSpec(
        topic="university.determinant",
        symbols=[SymbolSpec(name="x")],
        givens=[Given(id="g1", kind="domain", symbol="x", domain="real")],
        goal=Goal(
            kind="determinant",
            matrix=[[num(1), num(2)], [num(3), num(4)]],
        ),
        text=TextSpec(mode="symbolic", template="det [[1,2],[3,4]]"),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
    )
    assert solve_item(determinant).answer.items == ["-2"]


def test_primitives_are_tri_state() -> None:
    x = sympy.Symbol("x")
    assert (
        expression_equiv(sympy.sin(x) ** 2 + sympy.cos(x) ** 2, sympy.Integer(1)).status
        == "passed"
    )
    assert expression_equiv(x, x + 1).status == "failed"
    assert numeric_equal(Fraction(1, 3), sympy.Rational(1, 3)).status == "passed"
    assert solution_set_equal(sympy.FiniteSet(2), sympy.Integer(2)).status == "passed"
    assert collection_equal([1, 2], [2, 1]).status == "passed"
    assert collection_equal([1, 2], [2, 1], ordered=True).status == "failed"
    assert (
        interval_equal(
            Interval(lower="0", upper="1", lower_open=False, upper_open=False),
            Interval(lower="0", upper="1", lower_open=False, upper_open=False),
        ).status
        == "passed"
    )
    assert matrix_equal([[1, 2]], [[1, 2]]).status == "passed"


def test_harness_blocks_wrong_key_and_bad_distractors() -> None:
    wrong_key = validate_item(linear_item(answer=Answer(kind="numeric", items=["5"])))
    assert wrong_key.report.status == "failed"
    assert any("contradicts" in finding for finding in wrong_key.report.findings)

    duplicate = validate_item(
        linear_item(
            distractors=[
                Distractor(value=num(4), misconception="COPY_KEY"),
                Distractor(value=num(4), misconception="COPY_AGAIN"),
            ]
        )
    )
    assert duplicate.report.status == "failed"
    assert duplicate.report.options[0].result.status == "failed"

    witness = validate_item(
        linear_item(),
        witnesses=[
            Witness(
                name="wrong",
                answer=Answer(kind="numeric", items=["5"]),
                expected="rejected",
            )
        ],
    )
    assert witness.report.status == "passed"
    assert witness.witnesses[0].passed


def test_harness_reports_inconclusive_without_a_counterexample() -> None:
    item = linear_item(
        distractors=[Distractor(value=num(7), misconception="INVERSE")],
        answer=None,
    )
    item = item.model_copy(
        update={"validation": ValidationSpec(primitives=[PrimitiveSpec(type="proof")])}
    )
    report = validate_item(item)
    assert report.report.status == "inconclusive"
    assert report.report.options[0].result.status == "inconclusive"


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
        distractors=[Distractor(value=Expr(param="d"), misconception="WRONG_CONSTANT")],
        text=TextSpec(mode="symbolic", template="Solve for x."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )
    template = MathTemplateSpec(
        topic="school.linear_equation",
        parameters=[
            ParameterSpec(name="a", values=["2"]),
            ParameterSpec(name="b", values=["3"]),
            ParameterSpec(name="c", values=["11"]),
            ParameterSpec(name="d", values=["5", "4"]),
        ],
        body=body,
    )
    report = validate_template(template)
    assert report.report.status == "failed"
    assert report.variants_checked == 2


def test_linear_candidate_migrates_to_ir_and_passes() -> None:
    template = linear_template_ir(math_candidate())
    report = validate_template(template, max_variants=512)
    assert report.report.status == "passed"
    assert report.variants_checked == 8


def test_linear_candidate_with_key_distractor_fails_ir_gate() -> None:
    candidate = math_candidate(
        distractors=[
            {
                "expression": "(c - b) / a",
                "reason_template": "Copies the correct answer.",
            }
        ]
    )
    report = validate_template(linear_template_ir(candidate), max_variants=512)
    assert report.report.status == "failed"


def _unused(_: PrimitiveResult) -> None:
    """Keep the helper import meaningful for type checkers."""


def test_truncated_variant_sweep_is_inconclusive() -> None:
    template = linear_template_ir(math_candidate())

    report = validate_template(template, max_variants=1)

    assert report.report.status == "inconclusive"
    assert report.variants_checked == 1
    assert report.variants_total == 8
    assert any("truncated" in finding for finding in report.report.findings)


def test_solution_set_unique_parameter_rejects_multiple_roots() -> None:
    from edcraft_validator.domains.math.validation.primitives import check_primitive

    primitive = PrimitiveSpec(type="solution_set", params={"unique": True})
    two_roots = sympy.FiniteSet(-1, 1)

    passed = check_primitive(
        primitive, expected=sympy.FiniteSet(2), actual=sympy.FiniteSet(2)
    )
    failed = check_primitive(primitive, expected=two_roots, actual=two_roots)

    assert passed.status == "passed"
    assert failed.status == "failed"
    assert "unique" in failed.reason
