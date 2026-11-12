"""Deterministic controlled renderer and option builder for polynomial MCQ."""

from __future__ import annotations

import random
from dataclasses import dataclass

from edcraft_validator.application.check_pilot.models import PolynomialFamily
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    derivative_via_coefficients,
    parse_polynomial,
    render_polynomial,
    semantic_mutations,
)

MIN_CHOICES = 2


class QuestionBuildError(ValueError):
    """The declared family cannot produce one safe question instance."""


@dataclass(frozen=True, slots=True)
class GeneratedInstance:
    problem: Polynomial
    expected: Polynomial
    expression: str
    question: str
    choices: tuple[str, ...]
    correct_index: int
    parameters: dict[str, int | str]
    distractors: tuple[str, ...]

    @property
    def answer(self) -> str:
        return render_polynomial(self.expected)


def validate_assignment(
    family: PolynomialFamily, coefficients: tuple[int, ...]
) -> None:
    if len(coefficients) != family.degree + 1:
        raise QuestionBuildError("assignment does not match the declared degree")
    for exponent, value in enumerate(coefficients):
        domain = family.coefficients[exponent]
        if value not in domain.values:
            raise QuestionBuildError(
                f"assignment value for exponent {exponent} is outside its domain"
            )
    if coefficients[-1] == 0:
        raise QuestionBuildError("the leading coefficient must be nonzero")


def _instance_seed(seed: int, coefficients: tuple[int, ...]) -> int:
    value = seed & 0x7FFF_FFFF
    for coefficient in coefficients:
        value = (value * 131 + coefficient + 10_007) & 0xFFFF_FFFF_FFFF_FFFF
    return value


def build_instance(
    family: PolynomialFamily,
    coefficients: tuple[int, ...],
    *,
    seed: int,
    num_distractors: int | None = None,
) -> GeneratedInstance:
    """Render one instance without a provider or any model-authored text."""
    validate_assignment(family, coefficients)
    problem = Polynomial.from_coefficients(coefficients)
    expected = derivative_via_coefficients(problem)
    expression = render_polynomial(problem)
    question = f"Differentiate p(x) = {expression} with respect to x."
    required = family.num_distractors if num_distractors is None else num_distractors
    if required < 1:
        raise QuestionBuildError("at least one distractor is required")
    rng = random.Random(_instance_seed(seed, coefficients))
    wrong_values = semantic_mutations(expected, required, rng=rng)
    if len(wrong_values) < required:
        raise QuestionBuildError(
            "the bounded mutation set could not supply distinct wrong options"
        )
    seen: set[Polynomial] = {expected}
    wrong_texts: list[str] = []
    for wrong in wrong_values:
        text = render_polynomial(wrong)
        parsed = parse_polynomial(text)
        if parsed != wrong or parsed == expected or parsed in seen:
            raise QuestionBuildError("generated distractor failed its own check")
        seen.add(parsed)
        wrong_texts.append(text)
    answer_text = render_polynomial(expected)
    choices = [answer_text, *wrong_texts]
    rng.shuffle(choices)
    correct_index = choices.index(answer_text)
    parameters: dict[str, int | str] = {
        f"a{exponent}": coefficient for exponent, coefficient in enumerate(coefficients)
    }
    parameters["degree"] = family.degree
    parameters["variable"] = family.variable
    return GeneratedInstance(
        problem=problem,
        expected=expected,
        expression=expression,
        question=question,
        choices=tuple(choices),
        correct_index=correct_index,
        parameters=parameters,
        distractors=tuple(wrong_texts),
    )


def guard_instance(instance: GeneratedInstance, *, num_distractors: int) -> list[str]:
    """Application-owned correctness guard independent of a compiled recipe."""
    findings: list[str] = []
    try:
        problem = parse_polynomial(instance.expression)
    except ValueError as exc:
        return [f"expression does not parse: {exc}"]
    expected = derivative_via_coefficients(problem)
    if expected != instance.expected:
        findings.append("expected derivative disagrees with coefficient arithmetic")
    if parse_polynomial(instance.answer) != expected:
        findings.append("answer does not equal the independently derived derivative")
    parsed_choices: list[Polynomial] = []
    for choice in instance.choices:
        try:
            parsed_choices.append(parse_polynomial(choice))
        except ValueError:
            findings.append("a choice does not parse as a polynomial")
            continue
    if len(parsed_choices) != len(instance.choices):
        return findings
    if len(parsed_choices) != num_distractors + 1:
        findings.append("choice count does not match the requested distractors")
    if parsed_choices[instance.correct_index] != expected:
        findings.append("the keyed choice is not the derived derivative")
    wrong_choices = [
        value
        for index, value in enumerate(parsed_choices)
        if index != instance.correct_index
    ]
    if any(value == expected for value in wrong_choices):
        findings.append("a distractor equals the correct answer")
    if len(set(wrong_choices)) != len(wrong_choices):
        findings.append("distractor options are not distinct")
    if instance.expression not in instance.question:
        findings.append("the rendered question does not show the polynomial")
    return findings


__all__ = [
    "GeneratedInstance",
    "MIN_CHOICES",
    "QuestionBuildError",
    "build_instance",
    "guard_instance",
    "validate_assignment",
]
