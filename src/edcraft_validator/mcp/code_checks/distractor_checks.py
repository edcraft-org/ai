"""Checks and selection helpers for template distractors."""

import itertools
from typing import Any

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    TemplateValidationError,
)
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.domains.code.question_values import (
    _validate_distractor_type,
    _validate_distractor_value,
    _validate_distractors,
)
from edcraft_validator.domains.code.text_rendering import render_template
from edcraft_validator.mcp.code_checks.validation_context import (
    CodeValidationContext,
    DistractorCandidate,
)
from edcraft_validator.value_comparison import equivalent


def eligible_case_indices(candidates, answers):
    """Filter collisions only; malformed expressions and values remain failures."""
    result = []
    for index, answer in enumerate(answers):
        values = [candidate.values[index] for candidate in candidates]
        if any(equivalent(value, answer) for value in values):
            continue
        if any(equivalent(a, b) for a, b in itertools.combinations(values, 2)):
            continue
        result.append(index)
    return result


def check_proposed_distractor_selection(
    context: CodeValidationContext,
) -> None:
    """Select only model-proposed distractors, without adding fallbacks."""
    count = context.num_distractors
    if count is None:
        raise ValueError("a required distractor count must be provided")
    try:
        context.template, context.candidates, context.eligible_indices = (
            _select_distractors(
                context.template,
                context.inputs_cases,
                context.canonical_answers,
                context.candidates,
                num_distractors=count,
            )
        )
    except TemplateValidationError as exc:
        if exc.code == "DISTRACTOR_SELECTION_FAILED":
            rows = _failure_diagnostics(context)
            exc.context.update(
                cases=len(context.inputs_cases),
                distractor_diagnostics=rows[:16],
                diagnostics_truncated=len(rows) > 16,
            )
        raise


def _failure_diagnostics(context: CodeValidationContext) -> list[dict[str, Any]]:
    """One counterexample per bad recipe or colliding pair, without re-execution."""
    rows = []
    valid = []
    for candidate in context.candidates:
        recipe_id = f"D{candidate.index + 1}"
        if candidate.expression is None:
            rows.append({"recipe_id": recipe_id, "kind": "invalid_expression"})
            continue
        values = []
        for inputs, answer in zip(
            context.inputs_cases, context.canonical_answers, strict=True
        ):
            try:
                value = candidate.expression.evaluate(inputs)
                _validate_distractor_value(inputs, answer, value, candidate.index)
                render_template(
                    context.template.distractors[candidate.index].reason_template,
                    inputs,
                )
            except (
                TemplateValidationError,
                ArithmeticError,
                TypeError,
                ValueError,
            ) as exc:
                rows.append(
                    {
                        "recipe_id": recipe_id,
                        "kind": getattr(exc, "code", "EXPRESSION_EVALUATION_FAILED"),
                        "inputs": inputs,
                        "answer": answer,
                    }
                )
                break
            values.append(value)
        else:
            valid.append((recipe_id, values))
    for (first_id, first), (second_id, second) in itertools.combinations(valid, 2):
        for inputs, left, right in zip(
            context.inputs_cases, first, second, strict=True
        ):
            if equivalent(left, right):
                rows.append(
                    {
                        "recipe_id": second_id,
                        "other_recipe_id": first_id,
                        "kind": "DISTRACTOR_DUPLICATE",
                        "inputs": inputs,
                        "value": left,
                    }
                )
                break
    return rows


def check_distractors(context: CodeValidationContext) -> None:
    """Validate every selected distractor across the checked samples."""
    for candidate in context.candidates:
        if candidate.values is not None:
            continue
        if candidate.expression is None:
            raise AssertionError("validated distractor is missing its expression")
        candidate.values = [
            candidate.expression.evaluate(inputs) for inputs in context.inputs_cases
        ]
    for case_index in context.eligible_indices:
        inputs = context.inputs_cases[case_index]
        expected_answer = context.canonical_answers[case_index]
        generated = [
            candidate.values[case_index]
            for candidate in context.candidates
            if candidate.values is not None
        ]
        if len(generated) != len(context.candidates):
            raise AssertionError("validated distractor is missing computed values")
        _validate_distractors(inputs, expected_answer, generated)


def _select_distractors(
    template: CodeTemplateCandidate,
    inputs_cases: list[dict[str, ParameterValue]],
    expected_answers: list[Any],
    candidates: list[DistractorCandidate],
    *,
    num_distractors: int,
) -> tuple[CodeTemplateCandidate, list[DistractorCandidate], list[int]]:
    _precompute_candidate_vectors(template, inputs_cases, expected_answers, candidates)
    failures: list[str] = []
    best = None
    minimum = len(inputs_cases)

    for candidate_indexes in itertools.combinations(
        range(len(template.distractors)), num_distractors
    ):
        selected = [candidates[index] for index in candidate_indexes]
        rejection = next(
            (candidate.rejection for candidate in selected if candidate.rejection),
            None,
        )
        if rejection is not None:
            rendered_indexes = ",".join(str(index) for index in candidate_indexes)
            failures.append(f"candidates {rendered_indexes}: {rejection}")
            continue
        eligible = eligible_case_indices(selected, expected_answers)
        if best is None or len(eligible) > len(best[2]):
            best = (candidate_indexes, selected, eligible)
        if len(eligible) == len(inputs_cases):
            break

    if best is not None and len(best[2]) >= minimum:
        indexes, selected, eligible = best
        selected_template = template.model_copy(
            update={"distractors": [template.distractors[i] for i in indexes]},
            deep=True,
        )
        return selected_template, selected, eligible

    detail = "; ".join(failures[:3]) or "not enough candidates"
    raise TemplateValidationError(
        f"no set of {num_distractors} distractors passes all sampled cases "
        f"(need {minimum}/{len(inputs_cases)}, best "
        f"{len(best[2]) if best else 0}): {detail}",
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
            prefix = f"candidate {candidate.index}: "
            if not candidate.rejection.startswith(prefix):
                candidate.rejection = f"{prefix}{candidate.rejection}"
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
                _validate_distractor_type(
                    inputs, expected_answer, value, candidate.index
                )
                render_template(
                    template.distractors[candidate.index].reason_template, inputs
                )
        except (TemplateValidationError, ArithmeticError, TypeError, ValueError) as exc:
            candidate.rejection = f"candidate {candidate.index}: {exc}"
        else:
            candidate.values = values
