"""Deterministic question-expansion tests for the math domain."""

from fractions import Fraction

import pytest
from math_helpers import math_candidate

from edcraft_validator.domains.math.math_schemas import (
    MathValidationSummary,
    ValidatedMathTemplate,
    render_linear_equation,
)
from edcraft_validator.domains.math.question_generator import (
    generate_math_question,
)
from edcraft_validator.domains.math.safe_linear import format_fraction
from edcraft_validator.validation.validation_contracts import ValidationEvidence


def validated(candidate, artifact_id: str = "artifact-1") -> ValidatedMathTemplate:
    return ValidatedMathTemplate(
        artifact_id=artifact_id,
        template=candidate,
        validation=MathValidationSummary(
            combinations_checked=8,
            max_combinations=8,
            evidence=[
                ValidationEvidence(
                    check="math_validate_answers_and_distractors",
                    status="passed",
                )
            ],
        ),
    )


def test_same_seed_produces_an_identical_instance() -> None:
    artifact = validated(math_candidate())

    first = generate_math_question(artifact, 7)
    second = generate_math_question(artifact, 7)

    assert first == second
    assert first.artifact_id == "artifact-1"
    assert first.requires_manual_review is True


def test_different_seeds_are_reproducible() -> None:
    artifact = validated(math_candidate())

    for seed in (0, 1, 2, 42, -7):
        assert generate_math_question(artifact, seed) == generate_math_question(
            artifact, seed
        )


def test_generated_instance_has_consistent_exact_fields() -> None:
    artifact = validated(math_candidate())

    instance = generate_math_question(artifact, 3)

    assert instance.template_id == artifact.template.template_id
    assert set(instance.parameters) == {"a", "b", "c"}
    assert all(type(value) is int for value in instance.parameters.values())
    answer = Fraction(instance.answer)
    assert instance.choices[instance.correct_index] == instance.answer
    assert len(instance.choices) == len(set(instance.choices)) == 4
    assert instance.question == f"Solve for x: {instance.equation}"
    assert instance.equation == render_linear_equation(
        instance.parameters["a"],
        instance.parameters["b"],
        instance.parameters["c"],
    )
    assert answer == Fraction(
        instance.parameters["c"] - instance.parameters["b"],
        instance.parameters["a"],
    )


def test_generated_equation_renders_a_negative_constant_cleanly() -> None:
    artifact = validated(
        math_candidate(
            parameters=[
                {"name": "a", "values": [2]},
                {"name": "b", "values": [-6]},
                {"name": "c", "values": [5]},
            ]
        )
    )

    instance = generate_math_question(artifact, 0)

    assert instance.equation == "2x - 6 = 5"
    assert instance.question == "Solve for x: 2x - 6 = 5"


@pytest.mark.parametrize(
    ("a", "b", "c", "expected"),
    [
        (3, -6, -1, "3x - 6 = -1"),
        (2, 3, 7, "2x + 3 = 7"),
        (1, 2, 4, "x + 2 = 4"),
        (-1, 2, 4, "-x + 2 = 4"),
        (1, 0, 4, "x = 4"),
        (2, 0, -5, "2x = -5"),
    ],
)
def test_linear_equation_rendering(a: int, b: int, c: int, expected: str) -> None:
    assert render_linear_equation(a, b, c) == expected


def test_fractional_answers_are_exact_strings() -> None:
    artifact = validated(
        math_candidate(
            parameters=[
                {"name": "a", "values": [3]},
                {"name": "b", "values": [2]},
                {"name": "c", "values": [7]},
            ]
        )
    )

    instance = generate_math_question(artifact, 11)

    assert instance.answer == "5/3"
    assert instance.choices[instance.correct_index] == "5/3"
    assert format_fraction(Fraction(5, 3)) in instance.choices


def test_generator_refuses_unchecked_distractor_collisions() -> None:
    artifact = validated(
        math_candidate(
            parameters=[
                {"name": "a", "values": [1]},
                {"name": "b", "values": [2]},
                {"name": "c", "values": [5]},
            ],
            distractors=[
                {"expression": "(c - b)", "reason_template": "Forgets to divide."},
                {"expression": "(c + b) / a", "reason_template": "Adds b."},
                {"expression": "(c - b + 1) / a", "reason_template": "Off by one."},
            ],
        )
    )

    with pytest.raises(ValueError, match="Could not produce"):
        generate_math_question(artifact, 0)
