"""Deterministically expand validated math templates into equations."""

from __future__ import annotations

import hashlib
from itertools import product

from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    ValidatedMathTemplate,
    render_math_text,
)
from edcraft_validator.domains.math.safe_linear import (
    evaluate_expression,
    format_fraction,
)


def generate_math_question(
    validated: ValidatedMathTemplate, seed: int
) -> MathQuestionInstance:
    """Expand one validated template without AI calls or external I/O."""
    template = validated.template
    parameters = template.parameters
    combinations = [
        dict(zip((parameter.name for parameter in parameters), values, strict=True))
        for values in product(*(parameter.values for parameter in parameters))
    ]
    if not combinations:
        raise ValueError("validated template has an empty parameter domain")
    start = _seeded_index(
        template.template_id, seed, "parameter-combination", len(combinations)
    )
    for offset in range(len(combinations)):
        values = combinations[(start + offset) % len(combinations)]
        try:
            return _build_instance(validated, seed, values)
        except ValueError:
            continue
    raise ValueError("Could not produce a usable question from this template")


def _build_instance(
    validated: ValidatedMathTemplate, seed: int, values: dict[str, int]
) -> MathQuestionInstance:
    template = validated.template
    answer_value = evaluate_expression(template.answer_expression, values)
    answer = format_fraction(answer_value)
    equation = render_math_text(template.equation_template, values)
    question = render_math_text(
        template.question_template, {**values, "equation": equation}
    )
    distractor_values = [
        evaluate_expression(recipe.expression, values)
        for recipe in template.distractors
    ]
    if any(value == answer_value for value in distractor_values):
        raise ValueError("a distractor coincides with the answer")
    distractor_choices = [format_fraction(value) for value in distractor_values]
    if len(distractor_choices) != len(set(distractor_choices)):
        raise ValueError("distractor choices are not distinct")
    choices = list(distractor_choices)
    correct_index = _seeded_index(
        template.template_id, seed, "correct-index", len(distractor_choices) + 1
    )
    choices.insert(correct_index, answer)
    return MathQuestionInstance(
        template_id=template.template_id,
        artifact_id=validated.artifact_id,
        seed=seed,
        parameters=values,
        equation=equation,
        question=question,
        choices=choices,
        correct_index=correct_index,
        answer=answer,
    )


def _seeded_index(template_id: str, seed: int, name: str, size: int) -> int:
    payload = f"{template_id}:{seed}:{name}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % size
