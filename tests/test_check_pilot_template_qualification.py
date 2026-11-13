"""Bounded family qualification is separate from check qualification."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    CoefficientDomain,
    PilotQualificationSettings,
    PolynomialFamily,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.application.check_pilot.qualification import qualify_template


def recipe(*, second_derivative: bool = False) -> CheckRecipeDefinition:
    steps = [
        RecipeStep(
            id="d1",
            operation="poly.differentiate",
            version="1",
            arguments={"polynomial": RecipeArgument(source="input", name="problem")},
        )
    ]
    expected = "d1"
    if second_derivative:
        steps.append(
            RecipeStep(
                id="d2",
                operation="poly.differentiate",
                version="1",
                arguments={"polynomial": RecipeArgument(source="step", name="d1")},
            )
        )
        expected = "d2"
    steps.append(
        RecipeStep(
            id="out",
            operation="poly.equivalent",
            version="1",
            arguments={
                "expected": RecipeArgument(source="step", name=expected),
                "actual": RecipeArgument(source="input", name="candidate"),
            },
        )
    )
    return CheckRecipeDefinition(steps=steps, output="out")


def family(**changes) -> PolynomialFamily:
    values = {
        "degree": 1,
        "coefficients": [
            CoefficientDomain(exponent=0, values=[-2, 0, 2]),
            CoefficientDomain(exponent=1, values=[1, 3]),
        ],
        "num_distractors": 3,
    }
    values.update(changes)
    return PolynomialFamily(**values)


def settings(**changes) -> PilotQualificationSettings:
    values = {
        "max_examples": 12,
        "max_execution_calls": 600,
        "timeout_seconds": 30.0,
    }
    values.update(changes)
    return PilotQualificationSettings(**values)


def test_valid_family_passes_separate_template_qualification():
    result = qualify_template(recipe(), family(), seed=3, settings=settings())
    assert result.status == "passed"
    assert result.checking_mode == "property_based"
    assert result.accepted_cases >= 2
    assert result.execution_calls > result.accepted_cases
    assert result.counterexample is None
    assert "No counterexample found in sampled cases" in result.findings
    assert result.versions["question_builder"] == "polynomial-mcq/1"


def test_wrong_pinned_recipe_fails_template_qualification():
    first = qualify_template(
        recipe(second_derivative=True), family(), seed=3, settings=settings()
    )
    second = qualify_template(
        recipe(second_derivative=True), family(), seed=3, settings=settings()
    )
    assert first.status == "failed"
    assert first.phase == "sampling"
    assert first.counterexample is not None
    assert first.counterexample == second.counterexample
    assert "assignment" in first.counterexample


def test_large_domain_is_sampled_not_enumerated():
    large = family(
        degree=3,
        coefficients=[
            CoefficientDomain(exponent=exponent, values=list(range(-4, 6)))
            for exponent in range(3)
        ]
        + [CoefficientDomain(exponent=3, values=list(range(1, 6)))],
    )
    result = qualify_template(
        recipe(), large, seed=9, settings=settings(max_examples=8)
    )
    assert result.status == "passed"
    assert result.accepted_cases < 100
    assert result.execution_calls < 600


@pytest.mark.parametrize(
    "values",
    [
        [{"exponent": 0, "values": [1, 1]}],
        [{"exponent": 0, "values": [21]}],
        [{"exponent": 1, "values": [1]}],
        [{"exponent": 0, "values": []}],
    ],
)
def test_invalid_declared_coefficient_domains_are_rejected(values):
    with pytest.raises(ValidationError):
        PolynomialFamily(
            degree=len(values),
            coefficients=[CoefficientDomain.model_validate(item) for item in values],
            num_distractors=3,
        )


def test_zero_leading_coefficient_domain_is_rejected():
    with pytest.raises(ValidationError, match="leading"):
        family(
            coefficients=[
                CoefficientDomain(exponent=0, values=[0, 1]),
                CoefficientDomain(exponent=1, values=[0, 1]),
            ]
        )


def test_missing_exponent_domain_is_rejected():
    with pytest.raises(ValidationError, match="exponent"):
        family(
            degree=2,
            coefficients=[
                CoefficientDomain(exponent=0, values=[1]),
                CoefficientDomain(exponent=2, values=[1]),
            ],
        )
