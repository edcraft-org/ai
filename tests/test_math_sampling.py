"""Bounded property-based sampling of a template's declared parameter domain."""

from __future__ import annotations

from fractions import Fraction

from math_helpers import arithmetic_ir_template, ir_candidate, quadratic_ir_template

from edcraft_validator.domains.math.ir.instantiate import (
    declared_domain_size,
    parameter_combinations,
    representative_item,
    sample_parameter_combinations,
)
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec, ParameterSpec
from edcraft_validator.domains.math.math_schemas import (
    MathValidationSummary,
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
    assert report.variants_checked == 12
    assert report.variants_total == 10_000


def test_representative_item_renders_from_a_large_domain() -> None:
    item = representative_item(_large_template())

    assert item.text.template.startswith("What is ")
    assert "{" not in item.text.template


def test_generation_draws_variants_beyond_the_validated_sample() -> None:
    template = _large_template()
    report = validate_template(template, max_variants=4, seed=0)

    assert report.report.status == "passed", report.report.findings
    artifact = ValidatedMathTemplate(
        artifact_id="artifact-large",
        template=ir_candidate(template),
        validation=MathValidationSummary(
            combinations_checked=report.variants_checked,
            max_combinations=report.variants_total,
            seed=report.seed,
            evidence=[
                ValidationEvidence(check="math_verify_item_spec", status="passed")
            ],
        ),
    )

    seen: set[tuple[str, str]] = set()
    for seed in range(20):
        instance = generate_math_question(artifact, seed)
        seen.add((str(instance.parameters["a"]), str(instance.parameters["b"])))

    assert len(seen) > report.variants_checked
