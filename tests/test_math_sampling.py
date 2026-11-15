"""Bounded property-based sampling of a template's declared parameter domain."""

from __future__ import annotations

from fractions import Fraction

from math_helpers import (
    arithmetic_ir_template,
    checked_summary,
    ir_candidate,
    quadratic_ir_template,
)

from edcraft_validator.domains.math.ir.instantiate import (
    declared_domain_size,
    parameter_combinations,
    representative_item,
    sample_parameter_combinations,
)
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.domains.math.math_schemas import (
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.validation.harness import validate_template
from edcraft_validator.validation.validation_contracts import ValidationEvidence


def _large_template() -> MathTemplateSpec:
    template = arithmetic_ir_template()
    values = [str(value) for value in range(-50, 50)]
    return MathTemplateSpec(
        topic=template.topic,
        parameters=[
            ParameterSpec(name="a", values=values),
            ParameterSpec(name="b", values=values),
        ],
        body=template.body,
    )


def test_large_domain_is_sampled_without_materialising_the_product() -> None:
    template = _large_template()

    assert declared_domain_size(template) == 10_000

    sample = sample_parameter_combinations(template, limit=20, seed=0)

    assert sample.declared_size == 10_000
    assert sample.whole_domain is False
    assert len(sample.combinations) == 20


def test_sampling_includes_each_axis_at_both_edges() -> None:
    sample = sample_parameter_combinations(
        _large_template(), limit=20, seed=0
    ).combinations

    assert sample[0] == {"a": Fraction(-50), "b": Fraction(-50)}
    assert sample[1] == {"a": Fraction(49), "b": Fraction(49)}
    assert {"a": Fraction(49), "b": Fraction(-50)} in sample
    assert {"a": Fraction(-50), "b": Fraction(49)} in sample
    assert {"a": Fraction(49), "b": Fraction(49)} in sample


def test_sampling_is_deterministic_per_seed() -> None:
    template = _large_template()

    first = sample_parameter_combinations(template, limit=25, seed=3)
    second = sample_parameter_combinations(template, limit=25, seed=3)
    other = sample_parameter_combinations(template, limit=25, seed=4)

    assert first == second
    assert first.combinations != other.combinations


def test_small_domain_is_enumerated_completely() -> None:
    template = quadratic_ir_template()

    assert declared_domain_size(template) == 4

    sample = sample_parameter_combinations(template, limit=100, seed=0)

    assert sample.whole_domain is True
    assert sample.combinations == parameter_combinations(template)


def test_validation_samples_a_large_domain_and_records_coverage() -> None:
    template = _large_template()

    report = validate_template(template, max_variants=12, seed=5)

    assert report.report.status == "passed", report.report.findings
    assert report.checking_mode == "property_based"
    assert report.seed == 5
    assert 1 <= report.examples_checked <= 12
    assert report.declared_domain_size == 10_000


def test_large_domain_sampling_is_deterministic_per_seed() -> None:
    template = _large_template()

    first = validate_template(template, max_variants=12, seed=5)
    second = validate_template(template, max_variants=12, seed=5)
    other = validate_template(template, max_variants=12, seed=6)

    assert first.model_dump() == second.model_dump()
    assert first.model_dump() != other.model_dump()


def test_a_large_domain_checks_no_more_than_the_variant_budget() -> None:
    template = _large_template()

    for max_variants in (1, 4, 12, 20):
        report = validate_template(template, max_variants=max_variants, seed=3)
        assert 1 <= report.examples_checked <= max_variants


def test_representative_item_renders_from_a_large_domain() -> None:
    item = representative_item(_large_template())

    assert item.text.template.startswith("What is ")
    assert "{" not in item.text.template


def test_a_single_wrong_parameter_value_rejects_the_template() -> None:
    def num(value: int) -> Expr:
        return Expr(num=str(value))

    def add(*args: Expr) -> Expr:
        return Expr(op="add", args=list(args))

    def sub(left: Expr, right: Expr) -> Expr:
        return Expr(op="sub", args=[left, right])

    def mul(*args: Expr) -> Expr:
        return Expr(op="mul", args=list(args))

    parameter = Expr(param="a")
    body = MathItemSpec(
        topic="school.evaluate",
        symbols=[SymbolSpec(name="x", domain="rational")],
        givens=[Given(id="x_domain", kind="domain", symbol="x", domain="rational")],
        goal=Goal(kind="evaluate", expr=add(parameter, num(1))),
        # Correct for a = 1 and a = 2, wrong for a = 3.
        answer_recipe=AnswerRecipe(
            kind="numeric",
            items=[
                add(
                    add(parameter, num(1)),
                    mul(sub(parameter, num(1)), sub(parameter, num(2))),
                )
            ],
        ),
        text=TextSpec(mode="symbolic", template="Evaluate {expr}."),
    )
    template = MathTemplateSpec(
        topic="school.evaluate",
        parameters=[ParameterSpec(name="a", values=["1", "2", "3"])],
        body=body,
    )

    report = validate_template(template)

    assert report.report.status == "failed"
    assert any(finding.startswith("variant a=3:") for finding in report.report.findings)


def test_generation_draws_variants_beyond_the_validated_sample() -> None:
    template = _large_template()
    report = validate_template(template, max_variants=4, seed=0)

    assert report.report.status == "passed", report.report.findings
    artifact = ValidatedMathTemplate(
        artifact_id="artifact-large",
        template=ir_candidate(template),
        validation=checked_summary(
            report,
            [ValidationEvidence(check="math_verify_item_spec", status="passed")],
        ),
    )

    seen: set[tuple[str, str]] = set()
    for seed in range(20):
        instance = generate_math_question(artifact, seed)
        seen.add((str(instance.parameters["a"]), str(instance.parameters["b"])))

    assert len(seen) > report.examples_checked
