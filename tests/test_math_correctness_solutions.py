"""Focused tests for the deterministic solution-set correctness handler."""

from __future__ import annotations

import pytest

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    AnswerInterval,
    CorrectnessRequest,
    EngineUnknown,
    EngineUnsupported,
    MathAnswer,
    MathProblem,
)
from edcraft_validator.domains.math.engine.solutions import check_solutions
from edcraft_validator.domains.math.ir.schema import Expr, Relation, SymbolSpec

# ---------------------------------------------------------------------------
# Closed-IR builders


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


def sqrt(inner: Expr) -> Expr:
    return Expr(op="sqrt", args=[inner])


def log(inner: Expr) -> Expr:
    return Expr(op="log", args=[inner])


def exp(inner: Expr) -> Expr:
    return Expr(op="exp", args=[inner])


def sin(inner: Expr) -> Expr:
    return Expr(op="sin", args=[inner])


def eq(lhs: Expr, rhs: Expr) -> Relation:
    return Relation(kind="eq", lhs=lhs, rhs=rhs)


def ne(lhs: Expr, rhs: Expr) -> Relation:
    return Relation(kind="ne", lhs=lhs, rhs=rhs)


def lt(lhs: Expr, rhs: Expr) -> Relation:
    return Relation(kind="lt", lhs=lhs, rhs=rhs)


def le(lhs: Expr, rhs: Expr) -> Relation:
    return Relation(kind="le", lhs=lhs, rhs=rhs)


def gt(lhs: Expr, rhs: Expr) -> Relation:
    return Relation(kind="gt", lhs=lhs, rhs=rhs)


def ge(lhs: Expr, rhs: Expr) -> Relation:
    return Relation(kind="ge", lhs=lhs, rhs=rhs)


def interval(
    lower: Expr | None,
    upper: Expr | None,
    *,
    lower_open: bool = True,
    upper_open: bool = True,
) -> AnswerInterval:
    return AnswerInterval(
        lower=lower,
        upper=upper,
        lower_open=lower_open,
        upper_open=upper_open,
    )


def set_answer(
    items: list[Expr] | None = None,
    intervals: list[AnswerInterval] | None = None,
) -> MathAnswer:
    kwargs: dict[str, object] = {}
    if items is not None:
        kwargs["items"] = items
    if intervals is not None:
        kwargs["intervals"] = intervals
    return MathAnswer(kind="set", **kwargs)


def expression_answer(expression: Expr) -> MathAnswer:
    return MathAnswer(kind="expression", expression=expression)


def tuple_answer(items: list[Expr]) -> MathAnswer:
    return MathAnswer(kind="tuple", items=items)


def problem(
    relations: list[Relation],
    *,
    solve_for: tuple[str, ...] = ("x",),
    symbols: list[SymbolSpec] | None = None,
    domain: str = "real",
) -> MathProblem:
    if symbols is None:
        symbols = [SymbolSpec(name=name) for name in solve_for]
    return MathProblem(
        operation="solve",
        symbols=symbols,
        relations=relations,
        solve_for=list(solve_for),
        domain=domain,
    )


def check(
    relations: list[Relation],
    answer: MathAnswer,
    *,
    solve_for: tuple[str, ...] = ("x",),
    symbols: list[SymbolSpec] | None = None,
    domain: str = "real",
):
    request = CorrectnessRequest(
        problem=problem(relations, solve_for=solve_for, symbols=symbols, domain=domain),
        answer=answer,
    )
    return check_solutions(EngineContext.create(request))


def negative(value: Expr) -> Expr:
    return sub(num(0), value)


# ---------------------------------------------------------------------------
# Univariate equations


def test_linear_equation_correct_and_missing_root_incorrect() -> None:
    relations = [eq(add(mul(num(2), sym("x")), num(3)), num(7))]
    assert check(relations, set_answer([num(2)])).outcome == "correct"
    assert check(relations, set_answer([num(3)])).outcome == "incorrect"
    assert check(relations, set_answer([], [])).outcome == "incorrect"


def test_every_original_relation_must_hold() -> None:
    relations = [gt(sym("x"), num(0)), eq(power(sym("x"), num(2)), num(4))]
    assert check(relations, set_answer([num(2)])).outcome == "correct"
    # The negative root is a solution of the equation but not of x > 0.
    assert (
        check(relations, set_answer([negative(num(2)), num(2)])).outcome == "incorrect"
    )


def test_symbol_assumptions_restrict_the_true_domain() -> None:
    positive = [SymbolSpec(name="x", positive=True)]
    nonzero = [SymbolSpec(name="x", nonzero=True)]
    relation = [eq(power(sym("x"), num(2)), num(4))]

    assert check(relation, set_answer([num(2)]), symbols=positive).outcome == "correct"
    assert (
        check(
            relation, set_answer([negative(num(2)), num(2)]), symbols=positive
        ).outcome
        == "incorrect"
    )
    assert (
        check(relation, set_answer([negative(num(2)), num(2)]), symbols=nonzero).outcome
        == "correct"
    )
    assert (
        check(
            relation, set_answer([num(0), negative(num(2)), num(2)]), symbols=nonzero
        ).outcome
        == "incorrect"
    )


def test_x_over_x_equals_one_excludes_zero() -> None:
    relations = [eq(div(sym("x"), sym("x")), num(1))]
    excluded_zero = set_answer(
        intervals=[
            interval(None, num(0)),
            interval(num(0), None, lower_open=True),
        ]
    )
    all_reals = set_answer(intervals=[interval(None, None)])

    assert check(relations, excluded_zero).outcome == "correct"
    assert check(relations, all_reals).outcome == "incorrect"
    assert check(relations, set_answer([], [])).outcome == "incorrect"


def test_nested_cancelled_denominator_hole_is_preserved() -> None:
    rational_identity = div(sub(power(sym("x"), num(2)), num(1)), sub(sym("x"), num(1)))
    relations = [eq(div(rational_identity, add(sym("x"), num(1))), num(1))]
    excluded = set_answer(
        intervals=[
            interval(None, negative(num(1))),
            interval(negative(num(1)), num(1)),
            interval(num(1), None, lower_open=True),
        ]
    )
    assert check(relations, excluded).outcome == "correct"
    assert check(relations, set_answer(intervals=[interval(None, None)])).outcome == (
        "incorrect"
    )


def test_cancelled_solution_at_a_hole_is_not_a_solution() -> None:
    # (x^2 - 1)/(x - 1) = 2 would be x = 1, exactly where the denominator is 0.
    relations = [
        eq(div(sub(power(sym("x"), num(2)), num(1)), sub(sym("x"), num(1))), num(2))
    ]
    assert check(relations, set_answer([], [])).outcome == "correct"
    assert check(relations, set_answer([num(1)])).outcome == "incorrect"


def test_irrational_roots_use_exact_sqrt_expressions() -> None:
    relations = [eq(power(sym("x"), num(2)), num(2))]
    correct = set_answer([sqrt(num(2)), negative(sqrt(num(2)))])
    missing = set_answer([sqrt(num(2))])

    assert check(relations, correct).outcome == "correct"
    assert check(relations, missing).outcome == "incorrect"


def test_high_degree_representable_root() -> None:
    relations = [eq(power(sym("x"), num(7)), num(2))]
    answer = set_answer([power(num(2), num("1/7"))])
    assert check(relations, answer).outcome == "correct"
    assert check(relations, set_answer([num(2)])).outcome == "incorrect"


def test_unrepresentable_high_degree_root_is_unsupported() -> None:
    relations = [eq(add(power(sym("x"), num(5)), negative(sym("x")), num(1)), num(0))]
    with pytest.raises(EngineUnsupported):
        check(relations, set_answer([], []))


def test_empty_solution_set_is_a_legitimate_answer() -> None:
    no_solutions = [eq(div(num(1), sym("x")), num(0))]
    assert check(no_solutions, set_answer([], [])).outcome == "correct"
    assert check(no_solutions, set_answer([num(0)])).outcome == "incorrect"

    unreal = [eq(add(power(sym("x"), num(2)), num(1)), num(0))]
    assert check(unreal, set_answer([], [])).outcome == "correct"
    assert check(unreal, set_answer([num(1)])).outcome == "incorrect"


def test_missing_finite_root_is_incorrect() -> None:
    relations = [eq(sub(power(sym("x"), num(3)), sym("x")), num(0))]
    assert (
        check(relations, set_answer([negative(num(1)), num(0), num(1)])).outcome
        == "correct"
    )
    assert (
        check(relations, set_answer([negative(num(1)), num(1)])).outcome == "incorrect"
    )
    assert (
        check(relations, set_answer([negative(num(1)), num(0), num(1), num(2)])).outcome
        == "incorrect"
    )


# ---------------------------------------------------------------------------
# Inequalities and unions


def test_inequality_union_and_endpoint_openness() -> None:
    relations = [gt(power(sym("x"), num(2)), num(1))]
    union = set_answer(
        intervals=[
            interval(None, negative(num(1))),
            interval(num(1), None),
        ]
    )
    assert check(relations, union).outcome == "correct"

    wrong_closed = set_answer(
        intervals=[
            interval(None, negative(num(1)), upper_open=False),
            interval(num(1), None),
        ]
    )
    assert check(relations, wrong_closed).outcome == "incorrect"
    assert (
        check(relations, set_answer(intervals=[interval(num(1), None)])).outcome
        == "incorrect"
    )


def test_closed_interval_solution_and_wrong_endpoint() -> None:
    relations = [le(power(sym("x"), num(2)), num(1))]
    correct = set_answer(
        intervals=[
            interval(num(-1), num(1), lower_open=False, upper_open=False),
        ]
    )
    assert check(relations, correct).outcome == "correct"
    assert (
        check(
            relations,
            set_answer(intervals=[interval(num(-1), num(1))]),
        ).outcome
        == "incorrect"
    )
    assert (
        check(
            relations,
            set_answer(
                intervals=[
                    interval(num(-1), num(2), lower_open=False, upper_open=False)
                ]
            ),
        ).outcome
        == "incorrect"
    )


def test_inequality_with_denominator_hole() -> None:
    rational = div(sub(power(sym("x"), num(2)), num(1)), sub(sym("x"), num(1)))
    relations = [ge(rational, num(0))]
    correct = set_answer(
        intervals=[
            interval(num(-1), num(1), lower_open=False),
            interval(num(1), None),
        ]
    )
    assert check(relations, correct).outcome == "correct"
    assert (
        check(
            relations,
            set_answer(intervals=[interval(num(-1), None, lower_open=False)]),
        ).outcome
        == "incorrect"
    )


def test_irrational_inequality_endpoints() -> None:
    relations = [le(power(sym("x"), num(2)), num(2))]
    answer = set_answer(
        intervals=[
            interval(
                negative(sqrt(num(2))),
                sqrt(num(2)),
                lower_open=False,
                upper_open=False,
            )
        ]
    )
    assert check(relations, answer).outcome == "correct"


# ---------------------------------------------------------------------------
# Domains and assumptions


def test_integer_domain_filters_non_integer_roots() -> None:
    irrational = [eq(power(sym("x"), num(2)), num(2))]
    assert check(irrational, set_answer([], []), domain="integer").outcome == "correct"
    assert (
        check(
            irrational,
            set_answer([negative(sqrt(num(2))), sqrt(num(2))]),
            domain="integer",
        ).outcome
        == "incorrect"
    )


def test_integer_domain_finite_and_interval_forms() -> None:
    relation = [eq(power(sym("x"), num(2)), num(4))]
    assert (
        check(
            relation,
            set_answer([negative(num(2)), num(2)]),
            domain="integer",
        ).outcome
        == "correct"
    )
    assert (
        check(relation, set_answer([num(2)]), domain="integer").outcome == "incorrect"
    )

    inequality = [le(power(sym("x"), num(2)), num(1))]
    assert (
        check(
            inequality,
            set_answer([negative(num(1)), num(0), num(1)]),
            domain="integer",
        ).outcome
        == "correct"
    )
    assert (
        check(
            inequality,
            set_answer(
                intervals=[
                    interval(num(-1), num(1), lower_open=False, upper_open=False)
                ]
            ),
            domain="integer",
        ).outcome
        == "correct"
    )


def test_rational_domain_filters_irrational_and_accepts_exact_fraction() -> None:
    irrational = [eq(power(sym("x"), num(2)), num(2))]
    assert check(irrational, set_answer([], []), domain="rational").outcome == "correct"
    assert (
        check(
            irrational,
            set_answer([negative(sqrt(num(2))), sqrt(num(2))]),
            domain="rational",
        ).outcome
        == "incorrect"
    )

    linear = [eq(add(div(sym("x"), num(2)), div(num(1), num(3))), num(0))]
    assert (
        check(linear, set_answer([num("-2/3")]), domain="rational").outcome == "correct"
    )
    assert check(linear, set_answer([num("-3/4")]), domain="rational").outcome == (
        "incorrect"
    )


def test_symbol_integer_assumption_restricts_real_problem_domain() -> None:
    symbols = [SymbolSpec(name="x", integer=True)]
    relations = [eq(power(sym("x"), num(2)), num(2))]
    assert check(relations, set_answer([], []), symbols=symbols).outcome == "correct"
    assert (
        check(
            relations,
            set_answer([negative(sqrt(num(2))), sqrt(num(2))]),
            symbols=symbols,
        ).outcome
        == "incorrect"
    )


def test_infinite_integer_solution_requires_an_infinite_answer() -> None:
    relations = [ne(sym("x"), num(0))]
    assert (
        check(
            relations,
            set_answer([negative(num(1)), num(1)]),
            domain="integer",
        ).outcome
        == "incorrect"
    )
    assert (
        check(
            relations,
            set_answer(
                intervals=[
                    interval(None, num(0)),
                    interval(num(0), None),
                ]
            ),
            domain="integer",
        ).outcome
        == "correct"
    )


# ---------------------------------------------------------------------------
# Answer kinds and unresolved candidates


def test_expression_singleton_answer() -> None:
    relations = [eq(sym("x"), num(2))]
    assert check(relations, expression_answer(num(2))).outcome == "correct"
    assert check(relations, expression_answer(num(3))).outcome == "incorrect"


def test_symbolic_candidate_cannot_be_collapsed_to_incorrect() -> None:
    symbols = [SymbolSpec(name="x"), SymbolSpec(name="a")]
    relations = [eq(power(sym("x"), num(2)), num(2))]
    with pytest.raises(EngineUnknown):
        check(relations, set_answer([sym("a")]), symbols=symbols)


# ---------------------------------------------------------------------------
# Unsupported and unknown mathematics


def test_parameterized_single_equation_is_unsupported() -> None:
    symbols = [SymbolSpec(name="x"), SymbolSpec(name="a")]
    relations = [eq(mul(sym("a"), sym("x")), num(1))]
    with pytest.raises(EngineUnsupported):
        check(relations, set_answer([num(1)]), symbols=symbols)


def test_nested_condition_set_is_unknown() -> None:
    relations = [eq(add(exp(sym("x")), sym("x")), num(0))]
    with pytest.raises(EngineUnknown):
        check(relations, set_answer([], []))


def test_periodic_trigonometric_solution_is_unsupported() -> None:
    equations = [eq(sin(sym("x")), num(0))]
    with pytest.raises(EngineUnsupported):
        check(equations, set_answer([], []))

    # SymPy returns only a principal-branch interval for this inequality, which
    # would silently discard every other period.
    inequalities = [gt(sin(sym("x")), num(0))]
    with pytest.raises(EngineUnsupported):
        check(inequalities, set_answer([], []))

    # A complete periodic result is still accepted.
    complete = [le(sin(sym("x")), num(1))]
    assert (
        check(complete, set_answer(intervals=[interval(None, None)])).outcome
        == "correct"
    )


def test_complete_exponential_and_logarithmic_inequalities() -> None:
    exponential = [gt(exp(sym("x")), num(1))]
    assert (
        check(exponential, set_answer(intervals=[interval(num(0), None)])).outcome
        == "correct"
    )
    assert (
        check(exponential, set_answer(intervals=[interval(num(1), None)])).outcome
        == "incorrect"
    )

    logarithmic = [gt(log(sym("x")), num(0))]
    assert (
        check(logarithmic, set_answer(intervals=[interval(num(1), None)])).outcome
        == "correct"
    )
    assert (
        check(logarithmic, set_answer(intervals=[interval(num(0), None)])).outcome
        == "incorrect"
    )


def test_exponential_and_logarithmic_equations_when_complete() -> None:
    exponential = [eq(exp(sym("x")), num(2))]
    assert check(exponential, set_answer([log(num(2))])).outcome == "correct"

    logarithmic = [eq(log(sym("x")), num(0))]
    assert check(logarithmic, set_answer([num(1)])).outcome == "correct"
    assert check(logarithmic, set_answer([negative(num(1))])).outcome == "incorrect"


# ---------------------------------------------------------------------------
# Linear systems


def three_by_three() -> tuple[list[Relation], list[SymbolSpec]]:
    x, y, z = sym("x"), sym("y"), sym("z")
    relations = [
        eq(add(x, y, z), num(6)),
        eq(add(mul(num(2), x), negative(y), z), num(3)),
        eq(add(x, mul(num(2), y), negative(z)), num(2)),
    ]
    symbols = [SymbolSpec(name="x"), SymbolSpec(name="y"), SymbolSpec(name="z")]
    return relations, symbols


def test_three_by_three_linear_system_unique_tuple() -> None:
    relations, symbols = three_by_three()
    assert (
        check(
            relations,
            tuple_answer([num(1), num(2), num(3)]),
            solve_for=("x", "y", "z"),
            symbols=symbols,
        ).outcome
        == "correct"
    )
    assert (
        check(
            relations,
            tuple_answer([num(1), num(2), num(4)]),
            solve_for=("x", "y", "z"),
            symbols=symbols,
        ).outcome
        == "incorrect"
    )


def test_underdetermined_linear_system_is_unsupported() -> None:
    relations = [eq(add(sym("x"), sym("y")), num(3))]
    symbols = [SymbolSpec(name="x"), SymbolSpec(name="y")]
    with pytest.raises(EngineUnsupported):
        check(
            relations,
            tuple_answer([num(1), num(2)]),
            solve_for=("x", "y"),
            symbols=symbols,
        )


def test_nonlinear_system_is_unsupported() -> None:
    relations = [eq(mul(sym("x"), sym("y")), num(1))]
    symbols = [SymbolSpec(name="x"), SymbolSpec(name="y")]
    with pytest.raises(EngineUnsupported):
        check(
            relations,
            tuple_answer([num(1), num(1)]),
            solve_for=("x", "y"),
            symbols=symbols,
        )


def test_extra_equations_are_never_ignored() -> None:
    relations = [
        eq(add(sym("x"), sym("y")), num(3)),
        eq(sub(sym("x"), sym("y")), num(1)),
        eq(add(sym("x"), sym("y")), num(4)),
    ]
    symbols = [SymbolSpec(name="x"), SymbolSpec(name="y")]
    with pytest.raises(EngineUnsupported, match="no unique admissible solution"):
        check(
            relations,
            tuple_answer([num(2), num(1)]),
            solve_for=("x", "y"),
            symbols=symbols,
        )
