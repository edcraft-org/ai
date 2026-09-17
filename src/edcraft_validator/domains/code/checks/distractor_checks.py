"""Checks and selection helpers for template distractors."""

import itertools
from typing import Any

from edcraft_validator.domains.code.checks.answer_checks import require_json_value
from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
    DistractorCandidate,
)
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    TemplateValidationError,
)
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.domains.code.text_rendering import render_template
from edcraft_validator.validation.validation_contracts import CheckResult
from edcraft_validator.value_comparison import equivalent, same_value_shape


def selected_count(context: CodeValidationContext) -> int | None:
    if context.num_distractors is not None:
        return context.num_distractors
    return context.original_distractor_count if context.corrected_cases else None


def check_selection(context: CodeValidationContext) -> CheckResult | None:
    """Select the first globally valid candidate combination when requested."""
    count = selected_count(context)
    if count is None:
        return None
    context.template, context.candidates = _select_distractors(
        context.template,
        context.inputs_cases,
        context.canonical_answers,
        context.candidates,
        num_distractors=count,
    )
    return CheckResult()


def check_distractors(context: CodeValidationContext) -> CheckResult:
    """Validate every selected distractor over the complete input domain."""
    for candidate in context.candidates:
        if candidate.values is not None:
            continue
        if candidate.expression is None:
            raise AssertionError("validated distractor is missing its expression")
        candidate.values = [
            candidate.expression.evaluate(inputs) for inputs in context.inputs_cases
        ]
    for case_index, (inputs, expected_answer) in enumerate(
        zip(context.inputs_cases, context.canonical_answers, strict=True)
    ):
        generated = [
            candidate.values[case_index]
            for candidate in context.candidates
            if candidate.values is not None
        ]
        if len(generated) != len(context.candidates):
            raise AssertionError("validated distractor is missing computed values")
        _validate_distractors(inputs, expected_answer, generated)
    return CheckResult()


def _select_distractors(
    template: CodeTemplateCandidate,
    inputs_cases: list[dict[str, ParameterValue]],
    expected_answers: list[Any],
    candidates: list[DistractorCandidate],
    *,
    num_distractors: int,
) -> tuple[CodeTemplateCandidate, list[DistractorCandidate]]:
    _precompute_candidate_vectors(template, inputs_cases, expected_answers, candidates)
    failures: list[str] = []

    for candidate_indexes in itertools.combinations(
        range(len(template.distractors)), num_distractors
    ):
        selected = [candidates[index] for index in candidate_indexes]
        rejection = next(
            (candidate.rejection for candidate in selected if candidate.rejection),
            None,
        )
        if rejection is None:
            rejection = _find_candidate_collision(selected, inputs_cases)
        if rejection is not None:
            rendered_indexes = ",".join(str(index) for index in candidate_indexes)
            failures.append(f"candidates {rendered_indexes}: {rejection}")
            continue
        recipes = [template.distractors[index] for index in candidate_indexes]
        selected_template = template.model_copy(
            update={"distractors": recipes}, deep=True
        )
        return selected_template, selected

    detail = "; ".join(failures[:3]) or "not enough candidates"
    raise TemplateValidationError(
        f"no set of {num_distractors} distractors is globally valid: {detail}",
        code="DISTRACTOR_SELECTION_FAILED",
        field="distractors",
    )


def _precompute_candidate_vectors(
    template: CodeTemplateCandidate,
    inputs_cases: list[dict[str, ParameterValue]],
    expected_answers: list[Any],
    candidates: list[DistractorCandidate],
) -> None:
    for candidate in candidates:
        if candidate.rejection is not None:
            candidate.rejection = f"candidate {candidate.index}: {candidate.rejection}"
            continue
        if candidate.expression is None:
            raise AssertionError("distractor candidate is missing its expression")
        values = candidate.values or []
        try:
            if candidate.values is None:
                values = [
                    candidate.expression.evaluate(inputs) for inputs in inputs_cases
                ]
            for inputs, expected_answer, value in zip(
                inputs_cases, expected_answers, values, strict=True
            ):
                _validate_distractor_value(
                    inputs, expected_answer, value, candidate.index
                )
                render_template(
                    template.distractors[candidate.index].reason_template, inputs
                )
        except (TemplateValidationError, ArithmeticError, TypeError, ValueError) as exc:
            candidate.rejection = f"candidate {candidate.index}: {exc}"
        else:
            candidate.values = values


def _find_candidate_collision(
    candidates: list[DistractorCandidate],
    inputs_cases: list[dict[str, ParameterValue]],
) -> str | None:
    for first, second in itertools.combinations(candidates, 2):
        if first.values is None or second.values is None:
            raise AssertionError("valid distractor candidate is missing its values")
        for inputs, first_value, second_value in zip(
            inputs_cases, first.values, second.values, strict=True
        ):
            if equivalent(first_value, second_value):
                return (
                    f"candidate {second.index} duplicates candidate {first.index} "
                    f"for inputs {inputs}"
                )
    return None


def _validate_distractors(
    inputs: dict[str, ParameterValue], answer: Any, distractors: list[Any]
) -> None:
    for index, distractor in enumerate(distractors):
        _validate_distractor_value(inputs, answer, distractor, index)
        if any(equivalent(distractor, previous) for previous in distractors[:index]):
            raise TemplateValidationError(
                f"distractor {index} is duplicated for inputs {inputs}",
                code="DISTRACTOR_DUPLICATE",
                field=f"distractors.{index}",
                inputs=inputs,
            )


def _validate_distractor_value(
    inputs: dict[str, ParameterValue],
    answer: Any,
    distractor: Any,
    index: int,
) -> None:
    require_json_value(distractor, f"distractor {index}")
    if not same_value_shape(distractor, answer):
        raise TemplateValidationError(
            f"distractor {index} has the wrong type for inputs {inputs}",
            code="DISTRACTOR_TYPE_MISMATCH",
            field=f"distractors.{index}",
            inputs=inputs,
        )
    if equivalent(distractor, answer):
        raise TemplateValidationError(
            f"distractor {index} equals the answer for inputs {inputs}",
            code="DISTRACTOR_EQUALS_ANSWER",
            field=f"distractors.{index}",
            inputs=inputs,
        )
