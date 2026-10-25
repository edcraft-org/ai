"""Deterministically expand validated code templates into questions."""

from __future__ import annotations

import copy
import hashlib

from edcraft_validator.domains.code.code_schemas import (
    CodeQuestionInstance,
    GeneratedQuestion,
    TemplateValidationError,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.question_values import (
    _validate_distractors,
    validate_supported_answer,
)
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.domains.code.text_rendering import render_template


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
    # Cheap recipe/rendering checks only: no execution or model calls. Failed
    # variants are resampled with a fixed bound, never repaired with invented options.
    for attempt in range(32):
        inputs = {
            p.name: copy.deepcopy(
                _seeded_choice(
                    p.values, template.template_id, seed, f"{p.name}:{attempt}"
                )
            )
            for p in template.parameters
        }
        try:
            answer = answer_recipe.evaluate(inputs)
            validate_supported_answer(inputs, answer)
            distractors = [r.evaluate(inputs) for r in distractor_recipes]
            _validate_distractors(inputs, answer, distractors)
            question_text = render_template(
                template.question_template, inputs, require_all=True
            )
            break
        except TemplateValidationError:
            continue
    else:
        raise TemplateValidationError(
            "Could not produce a usable draft within 32 recipe attempts",
            code="GENERATION_ATTEMPTS_EXHAUSTED",
        )
    distractor_reasons = [
        render_template(recipe.reason_template, inputs)
        for recipe in template.distractors
    ]
    question = GeneratedQuestion(
        code=template.code,
        entry_function=template.entry_function,
        inputs=inputs,
        question=question_text,
        proposed_answer=answer,
        distractors=distractors,
        distractor_reasons=distractor_reasons,
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


def _seeded_choice[ValueT](
    values: list[ValueT], digest: str, seed: int, name: str
) -> ValueT:
    payload = f"{digest}:{seed}:{name}".encode()
    index = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % len(values)
    return values[index]
