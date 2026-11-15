"""Deterministically expand a finalised code template into a question.

Generation evaluates and renders the approved recipes without model calls or
per-instance execution, retrying unusable options a fixed number of times.
"""

from __future__ import annotations

import copy
from typing import Any

from edcraft_validator.domains.code.code_schemas import (
    CodeQuestionInstance,
    CodeTemplateCandidate,
    GeneratedQuestion,
    TemplateValidationError,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.domains.code.question_values import (
    _validate_distractors,
    validate_supported_answer,
)
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.domains.code.text_rendering import render_template
from edcraft_validator.domains.domain_support import seeded_index


def generate_code_question(
    validated: ValidatedCodeTemplate, seed: int
) -> CodeQuestionInstance:
    """Expand a validated template without AI calls or per-instance code execution."""
    template = validated.template
    names = tuple(p.name for p in template.parameters)
    answer_recipe = SafeExpression(template.answer_expression, names)
    distractor_recipes = [
        SafeExpression(r.expression, names) for r in template.distractors
    ]

    inputs, answer, distractors, question_text = _first_usable_draft(
        template, answer_recipe, distractor_recipes, seed
    )
    question = GeneratedQuestion(
        code=template.code,
        entry_function=template.entry_function,
        inputs=inputs,
        question=question_text,
        proposed_answer=answer,
        distractors=distractors,
        distractor_reasons=_distractor_reasons(template, inputs),
        answer_target=template.answer_target,
        question_type=template.question_type,
    )

    return CodeQuestionInstance(
        template_id=template.template_id,
        artifact_id=validated.artifact_id,
        seed=seed,
        parameters=inputs,
        question=question,
    )


def _first_usable_draft(
    template: CodeTemplateCandidate,
    answer_recipe: SafeExpression,
    distractor_recipes: list[SafeExpression],
    seed: int,
) -> tuple[dict[str, ParameterValue], Any, list[Any], str]:
    """Resample parameter values until the recipe checks accept a draft."""
    # Only recipe and rendering checks run here. A failed variant is resampled
    # a fixed number of times, and no invented option is substituted.
    for attempt in range(32):
        inputs = _seeded_inputs(template, seed, attempt)
        try:
            answer, distractors, question_text = _accepted_values(
                inputs, answer_recipe, distractor_recipes, template
            )
            return inputs, answer, distractors, question_text
        except TemplateValidationError:
            continue

    raise TemplateValidationError(
        "Could not produce a usable draft within 32 recipe attempts",
        code="GENERATION_ATTEMPTS_EXHAUSTED",
    )


def _seeded_inputs(
    template: CodeTemplateCandidate,
    seed: int,
    attempt: int,
) -> dict[str, ParameterValue]:
    """Choose one reproducible value for every declared parameter."""
    return {
        p.name: copy.deepcopy(
            _seeded_choice(p.values, template.template_id, seed, f"{p.name}:{attempt}")
        )
        for p in template.parameters
    }


def _accepted_values(
    inputs: dict[str, ParameterValue],
    answer_recipe: SafeExpression,
    distractor_recipes: list[SafeExpression],
    template: CodeTemplateCandidate,
) -> tuple[Any, list[Any], str]:
    """Evaluate one draft and reject it when its recipes are unusable."""
    answer = answer_recipe.evaluate(inputs)
    validate_supported_answer(inputs, answer)
    distractors = [recipe.evaluate(inputs) for recipe in distractor_recipes]
    _validate_distractors(inputs, answer, distractors)
    question_text = render_template(
        template.question_template, inputs, require_all=True
    )
    return answer, distractors, question_text


def _distractor_reasons(
    template: CodeTemplateCandidate,
    inputs: dict[str, ParameterValue],
) -> list[str]:
    return [
        render_template(recipe.reason_template, inputs)
        for recipe in template.distractors
    ]


def _seeded_choice[ValueT](
    values: list[ValueT], digest: str, seed: int, name: str
) -> ValueT:
    return values[seeded_index(digest, seed, name, len(values))]
