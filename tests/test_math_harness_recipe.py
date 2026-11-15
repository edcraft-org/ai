"""Recipe harness: engine correctness and form shape, kept as separate oracles."""

from __future__ import annotations

import pytest
from hypothesis.errors import Unsatisfiable
from math_helpers import quadratic_ir_template

from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    RecipeInterval,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.domains.math.validation.harness import (
    validate_item,
    validate_template,
)


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


def power(base: Expr, exponent: Expr) -> Expr:
    return Expr(op="pow", args=[base, exponent])


def expand_item(
    *,
    recipe: AnswerRecipe | None = None,
    distractors: list[Distractor] | None = None,
) -> MathItemSpec:
    return _item(
        goal=Goal(
            kind="expand",
            expr=mul(add(sym("x"), num(1)), add(sym("x"), num(2))),
        ),
        recipe=recipe,
        distractors=distractors,
    )


def factor_item(
    *,
    recipe: AnswerRecipe | None = None,
    distractors: list[Distractor] | None = None,
) -> MathItemSpec:
    return _item(
        goal=Goal(
            kind="factor",
            expr=add(power(sym("x"), num(2)), add(mul(num(3), sym("x")), num(2))),
        ),
        recipe=recipe,
        distractors=distractors,
    )


def _item(
    *,
    goal: Goal,
    recipe: AnswerRecipe | None,
    distractors: list[Distractor] | None = None,
) -> MathItemSpec:
    return MathItemSpec(
        topic="school.recipe",
        symbols=[SymbolSpec(name="x")],
        givens=[Given(id="g1", kind="domain", symbol="x", domain="real")],
        goal=goal,
        answer_recipe=recipe,
        distractors=distractors or [],
        text=TextSpec(mode="symbolic", template="Rewrite the expression."),
    )


def expanded_recipe() -> AnswerRecipe:
    return AnswerRecipe(
        kind="expression",
        items=[add(power(sym("x"), num(2)), add(mul(num(3), sym("x")), num(2)))],
    )


def factored_recipe() -> AnswerRecipe:
    return AnswerRecipe(
        kind="expression",
        items=[mul(add(sym("x"), num(1)), add(sym("x"), num(2)))],
    )


def check_named(report, name: str):
    matches = [item for item in report.report.checks if item.check == name]
    assert len(matches) == 1, report.report.checks
    return matches[0]


def test_expanded_answer_passes_both_oracles() -> None:
    item = expand_item(recipe=expanded_recipe())
    report = validate_item(item)
    form_report = validate_item(item, aspect="form")

    assert report.report.status == "passed", report.report.findings
    assert check_named(report, "engine_correctness").status == "passed"
    assert check_named(report, "engine_correctness").evidence["outcome"] == "correct"
    assert form_report.report.status == "passed", form_report.report.findings
    assert check_named(form_report, "form").status == "passed"
    assert report.report.answer == "x^2 + 3*x + 2"


def test_each_aspect_reports_only_its_own_check() -> None:
    item = expand_item(recipe=expanded_recipe())

    assert [check.check for check in validate_item(item).report.checks] == [
        "engine_correctness"
    ]
    assert [
        check.check for check in validate_item(item, aspect="form").report.checks
    ] == ["form"]


def test_unexpanded_answer_is_correct_but_fails_the_form_check() -> None:
    item = expand_item(recipe=factored_recipe())
    report = validate_item(item)
    form_report = validate_item(item, aspect="form")

    assert report.report.status == "passed", report.report.findings
    assert check_named(report, "engine_correctness").status == "passed"
    assert form_report.report.status == "failed"
    form = check_named(form_report, "form")
    assert form.status == "failed"
    assert form.evidence["status"] == "fail"


def test_factored_answer_passes_a_factor_goal() -> None:
    report = validate_item(factor_item(recipe=factored_recipe()))

    assert report.report.status == "passed", report.report.findings


def test_expanded_answer_fails_a_factor_goal() -> None:
    item = factor_item(recipe=expanded_recipe())
    report = validate_item(item)
    form_report = validate_item(item, aspect="form")

    assert check_named(report, "engine_correctness").status == "passed"
    assert form_report.report.status == "failed"
    assert check_named(form_report, "form").status == "failed"


def test_wrong_recipe_fails_the_engine() -> None:
    wrong = AnswerRecipe(
        kind="expression", items=[add(power(sym("x"), num(2)), num(1))]
    )
    report = validate_item(expand_item(recipe=wrong))

    assert report.report.status == "failed"
    engine = check_named(report, "engine_correctness")
    assert engine.status == "failed"
    assert engine.evidence["outcome"] == "incorrect"


def test_distractor_equal_to_the_answer_is_rejected() -> None:
    report = validate_item(
        expand_item(
            recipe=expanded_recipe(),
            distractors=[
                Distractor(value=expanded_recipe().items[0], misconception="copy")
            ],
        )
    )

    assert report.report.status == "failed"
    assert report.report.options[0].result.status == "failed"
    assert "answers the problem correctly" in report.report.options[0].result.reason


def test_wrong_distractor_passes() -> None:
    report = validate_item(
        expand_item(
            recipe=expanded_recipe(),
            distractors=[
                Distractor(
                    value=add(power(sym("x"), num(2)), num(2)),
                    misconception="dropped term",
                )
            ],
        )
    )

    assert report.report.status == "passed", report.report.findings
    option = report.report.options[0]
    assert option.result.status == "passed"
    assert option.result.evidence["engine"]["outcome"] == "incorrect"


def test_unsupported_goal_fails_closed() -> None:
    item = _item(
        goal=Goal(kind="limit", expr=sym("x"), point=num(0)),
        recipe=AnswerRecipe(kind="numeric", items=[num(0)]),
    )
    report = validate_item(item)

    assert report.report.status == "failed"
    engine = check_named(report, "engine_correctness")
    assert engine.status == "failed"
    assert "cannot grade" in engine.reason


def test_interval_answer_fails_closed() -> None:
    item = _item(
        goal=Goal(kind="evaluate", expr=add(num(1), num(1))),
        recipe=AnswerRecipe(
            kind="interval",
            interval=RecipeInterval(lower=num(-1), upper=num(1)),
        ),
    )
    report = validate_item(item)

    assert report.report.status == "failed"
    assert (
        check_named(report, "engine_correctness").evidence["outcome"] == "unsupported"
    )


def test_template_without_a_recipe_is_rejected() -> None:
    template = MathTemplateSpec(
        topic="school.recipe",
        parameters=[ParameterSpec(name="a", values=["1", "2"])],
        body=_item(
            goal=Goal(kind="evaluate", expr=add(param("a"), num(1))),
            recipe=None,
        ),
    )
    report = validate_template(template)

    assert report.report.status == "failed"
    assert "answer_recipe" in report.report.findings[0]


def test_recipe_is_graded_for_every_variant() -> None:
    template = MathTemplateSpec(
        topic="school.recipe",
        parameters=[ParameterSpec(name="a", values=["1", "2", "3"])],
        body=_item(
            goal=Goal(kind="evaluate", expr=add(param("a"), num(1))),
            recipe=AnswerRecipe(kind="numeric", items=[add(param("a"), num(1))]),
        ),
    )
    report = validate_template(template)

    assert report.report.status == "passed", report.report.findings
    assert report.examples_checked == 3


@pytest.mark.parametrize("values", [["1", "2"], ["2", "3"]])
def test_a_recipe_that_is_wrong_for_any_variant_blocks_the_template(
    values: list[str],
) -> None:
    template = MathTemplateSpec(
        topic="school.recipe",
        parameters=[ParameterSpec(name="a", values=values)],
        body=_item(
            goal=Goal(kind="evaluate", expr=mul(param("a"), num(2))),
            recipe=AnswerRecipe(kind="numeric", items=[add(param("a"), num(2))]),
        ),
    )
    report = validate_template(template)

    assert report.report.status == "failed"
    assert any("engine_correctness" in finding for finding in report.report.findings)


def test_form_sensitive_goals_apply_the_form_rule_to_distractors() -> None:
    expanded = Distractor(value=expanded_recipe().items[0], misconception="expanded")
    report = validate_item(
        factor_item(recipe=factored_recipe(), distractors=[expanded]), aspect="form"
    )

    assert report.report.status == "failed"
    assert report.report.options[0].result.check == "distractor_form"
    assert any("option 0: distractor form" in f for f in report.report.findings)


def _one_parameter_template(values: list[str]) -> MathTemplateSpec:
    return MathTemplateSpec(
        topic="school.recipe",
        parameters=[ParameterSpec(name="a", values=values)],
        body=_item(
            goal=Goal(kind="evaluate", expr=add(param("a"), num(1))),
            recipe=AnswerRecipe(kind="numeric", items=[add(param("a"), num(1))]),
        ),
    )


def test_inconclusive_variant_makes_the_template_inconclusive(monkeypatch) -> None:
    from edcraft_validator.domains.math.validation import harness

    def undecided(*args, **kwargs):
        return harness.HarnessReport(
            report=harness.ValidationReport(
                status="inconclusive", findings=["the engine could not decide"]
            )
        )

    monkeypatch.setattr(harness, "validate_item", undecided)

    report = validate_template(_one_parameter_template(["1", "2"]))

    assert report.report.status == "inconclusive"
    assert any("could not decide" in finding for finding in report.report.findings)


def test_unsatisfiable_assumptions_are_rejected(monkeypatch) -> None:
    from edcraft_validator.domains.math.validation import harness

    def unsatisfiable(self, *args, **kwargs):
        raise Unsatisfiable("every generated combination was assumed away")

    monkeypatch.setattr(harness.PropertyCheckRun, "check", unsatisfiable)

    report = validate_template(_one_parameter_template(["1", "2"]))

    assert report.report.status == "failed"
    assert report.report.findings == ["template has no parameter combinations"]


def test_no_valid_combinations_are_rejected() -> None:
    report = validate_template(_one_parameter_template(["not-a-number"]))

    assert report.report.status == "failed"
    assert report.report.findings == ["template has no parameter combinations"]


def test_invalid_literals_mixed_with_valid_ones_pass() -> None:
    report = validate_template(_one_parameter_template(["1", "not-a-number"]))

    assert report.report.status == "passed", report.report.findings
    assert report.examples_checked >= 1


def test_budget_exhaustion_without_a_failure_reports_the_budget() -> None:
    from edcraft_validator.validation import property_checks

    def exhausted(self) -> None:
        raise property_checks._BudgetExceeded()

    original = property_checks.PropertyCheckRun.reserve_execution
    try:
        property_checks.PropertyCheckRun.reserve_execution = exhausted
        report = validate_template(_one_parameter_template(["1", "2"]))
    finally:
        property_checks.PropertyCheckRun.reserve_execution = original

    assert report.report.status == "failed"
    assert any(
        "PROPERTY_CHECK_BUDGET_EXCEEDED" in finding
        for finding in report.report.findings
    )


def test_budget_after_a_recorded_failure_reports_that_failure() -> None:
    from edcraft_validator.validation import property_checks

    original = property_checks.PropertyCheckRun.reserve_execution
    calls = 0

    def budget_after_first(self) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise property_checks._BudgetExceeded()
        original(self)

    template = MathTemplateSpec(
        topic="school.recipe",
        parameters=[ParameterSpec(name="a", values=["1", "2"])],
        body=_item(
            goal=Goal(kind="evaluate", expr=add(param("a"), num(1))),
            recipe=AnswerRecipe(kind="numeric", items=[add(param("a"), num(2))]),
        ),
    )
    try:
        property_checks.PropertyCheckRun.reserve_execution = budget_after_first
        report = validate_template(template, max_variants=1)
    finally:
        property_checks.PropertyCheckRun.reserve_execution = original

    assert report.report.status == "failed"
    assert any(finding.startswith("variant ") for finding in report.report.findings)
    assert not any(
        "PROPERTY_CHECK_BUDGET_EXCEEDED" in finding
        for finding in report.report.findings
    )


def test_a_distractor_graded_correct_carries_a_finding() -> None:
    template = quadratic_ir_template()
    template = template.model_copy(
        update={
            "parameters": [
                ParameterSpec(name="p", values=["1"]),
                ParameterSpec(name="q", values=["1"]),
            ]
        }
    )

    report = validate_template(template)

    assert report.report.status == "failed"
    assert report.report.findings
    assert any("distractor" in finding for finding in report.report.findings)
