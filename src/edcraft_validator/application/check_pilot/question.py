"""Deterministic controlled renderer and option builder for polynomial MCQ."""

from __future__ import annotations

import random
from dataclasses import dataclass

from edcraft_validator.application.check_pilot.models import (
    PolynomialFamily,
    PolynomialRelation,
    SolveFamily,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    derivative_via_coefficients,
    parse_polynomial,
    render_polynomial,
    semantic_mutations,
)
from edcraft_validator.application.check_pilot.seeds import coefficient_seed
from edcraft_validator.application.check_pilot.solution_sets import (
    SolutionSet,
    SolutionSetError,
    question_text,
    render_relation,
    render_solution_set,
    sets_equal,
    solution_set_mutations,
    solve_relation_independently,
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
    rng = random.Random(coefficient_seed(seed, coefficients))
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


@dataclass(frozen=True, slots=True)
class SolveGeneratedInstance:
    relation: PolynomialRelation
    expected: SolutionSet
    expression: str
    relation_text: str
    question: str
    choices: tuple[str, ...]
    correct_index: int
    parameters: dict[str, int | str]
    distractors: tuple[SolutionSet, ...]

    @property
    def answer(self) -> str:
        return render_solution_set(self.expected)


def validate_solve_assignment(
    family: SolveFamily, coefficients: tuple[int, ...]
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


def build_solve_instance(
    family: SolveFamily,
    coefficients: tuple[int, ...],
    *,
    seed: int,
    num_distractors: int | None = None,
) -> SolveGeneratedInstance:
    """Render one complete solution-set question without any model text."""
    validate_solve_assignment(family, coefficients)
    relation = family.relation
    try:
        expected = solve_relation_independently(relation, coefficients)
    except SolutionSetError as exc:
        raise QuestionBuildError(
            f"the independent oracle rejected the case: {exc}"
        ) from None
    required = family.num_distractors if num_distractors is None else num_distractors
    if required < 1:
        raise QuestionBuildError("at least one distractor is required")
    rng = random.Random(coefficient_seed(seed, coefficients))
    wrong_sets = solution_set_mutations(
        relation, coefficients, expected, required, rng=rng
    )
    if len(wrong_sets) < required:
        raise QuestionBuildError(
            "the bounded mutation set could not supply distinct wrong options"
        )
    answer_text = render_solution_set(expected)
    wrong_texts = [render_solution_set(item) for item in wrong_sets]
    if len(set([answer_text, *wrong_texts])) != required + 1:
        raise QuestionBuildError("generated solution-set options are not distinct")
    choices = [answer_text, *wrong_texts]
    rng.shuffle(choices)
    correct_index = choices.index(answer_text)
    expression = render_polynomial(Polynomial.from_coefficients(coefficients))
    parameters: dict[str, int | str] = {
        f"a{exponent}": coefficient for exponent, coefficient in enumerate(coefficients)
    }
    parameters["degree"] = family.degree
    parameters["variable"] = family.variable
    parameters["relation"] = family.relation
    return SolveGeneratedInstance(
        relation=PolynomialRelation(relation=relation, coefficients=list(coefficients)),
        expected=expected,
        expression=expression,
        relation_text=render_relation(relation, coefficients),
        question=question_text(relation, coefficients),
        choices=tuple(choices),
        correct_index=correct_index,
        parameters=parameters,
        distractors=tuple(wrong_sets),
    )


def guard_solve_instance(
    instance: SolveGeneratedInstance, *, num_distractors: int
) -> list[str]:
    """Independent guard over structured sets; no rendered answer is parsed."""
    findings: list[str] = []
    try:
        expected = solve_relation_independently(
            instance.relation.relation, tuple(instance.relation.coefficients)
        )
    except SolutionSetError as exc:
        return [f"independent oracle rejected the relation: {exc}"]
    if not sets_equal(expected, instance.expected):
        findings.append("expected solution set disagrees with independent arithmetic")
    answer_text = render_solution_set(expected)
    if instance.answer != answer_text:
        findings.append("rendered answer does not match the independent solution set")
    if len(instance.choices) != num_distractors + 1:
        findings.append("choice count does not match the requested distractors")
    if len(set(instance.choices)) != len(instance.choices):
        findings.append("solution-set options are not distinct")
    if not 0 <= instance.correct_index < len(instance.choices):
        findings.append("correct index does not address a choice")
    elif instance.choices[instance.correct_index] != answer_text:
        findings.append("the keyed choice is not the independent solution set")
    wrong_texts = [
        text
        for index, text in enumerate(instance.choices)
        if index != instance.correct_index
    ]
    if any(text == answer_text for text in wrong_texts):
        findings.append("a distractor equals the correct answer")
    for distractor in instance.distractors:
        if sets_equal(distractor, expected):
            findings.append("a distractor is mathematically equal to the answer")
    rendered_distractors = {render_solution_set(item) for item in instance.distractors}
    if not rendered_distractors <= set(wrong_texts):
        findings.append("a rendered distractor is missing from the options")
    if instance.expression not in instance.question:
        findings.append("the rendered question does not show the polynomial")
    if instance.relation_text not in instance.question:
        findings.append("the rendered question does not show the relation")
    return findings


__all__ = [
    "GeneratedInstance",
    "MIN_CHOICES",
    "QuestionBuildError",
    "SolveGeneratedInstance",
    "build_instance",
    "build_solve_instance",
    "guard_instance",
    "guard_solve_instance",
    "validate_assignment",
    "validate_solve_assignment",
]
