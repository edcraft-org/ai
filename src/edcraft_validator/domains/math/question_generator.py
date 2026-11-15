"""Deterministically expand approved math templates into questions.

Generation evaluates the approved recipes and renders them. It rejects unusable
option combinations, such as choices that are not distinct, but it does not
re-grade the answer or the distractors. Correctness and form were checked at
authoring time by the engine and the form registry.
"""

from __future__ import annotations

from fractions import Fraction

from edcraft_validator.domains.domain_support import seeded_index
from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.instantiate import (
    compile_distractor_value,
    display_sympy_value,
    fraction_text,
    render_goal_display,
    render_item_text,
    sample_parameter_combinations,
)
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import MAX_IR_VARIANTS
from edcraft_validator.domains.math.validation.answers import compile_answer_recipe
from edcraft_validator.domains.math.validation.distinct import same_value


class UnusableVariant(ValueError):
    """One parameter combination cannot yield a sound question."""


def generate_math_question(
    validated: ValidatedMathTemplate, seed: int
) -> MathQuestionInstance:
    """Expand one approved template without AI calls, engine calls or external I/O."""
    template = validated.template
    if template.item is not None:
        return _generate_ir_question(validated, template.item, seed)
    raise ValueError("question generation requires a generic item template")


def _generate_ir_question(
    validated: ValidatedMathTemplate,
    template: MathTemplateSpec,
    seed: int,
) -> MathQuestionInstance:
    if template.body.answer_recipe is None:
        raise ValueError("the template declares no answer recipe")
    sample = sample_parameter_combinations(template, limit=MAX_IR_VARIANTS, seed=seed)
    combinations = sample.combinations
    if not combinations:
        raise ValueError("validated template has an empty parameter domain")
    start = seeded_index(
        validated.template.template_id, seed, "parameter-combination", len(combinations)
    )
    for offset in range(len(combinations)):
        values = combinations[(start + offset) % len(combinations)]
        try:
            return _build_ir_instance(validated, template, seed, values)
        except (MathCompileError, UnusableVariant):
            continue
    raise ValueError("Could not produce a usable question from this template")


def _build_ir_instance(
    validated: ValidatedMathTemplate,
    template: MathTemplateSpec,
    seed: int,
    values: dict[str, Fraction],
) -> MathQuestionInstance:
    """Evaluate the approved recipes and render them. Nothing is solved here."""
    body = template.body
    recipe = body.answer_recipe
    if recipe is None:  # pragma: no cover - guarded by _generate_ir_question
        raise UnusableVariant("the template declares no answer recipe")
    try:
        compiled = compile_answer_recipe(recipe, body.symbols, values)
    except MathCompileError as exc:
        raise UnusableVariant(f"the answer recipe does not compile: {exc}") from exc
    answer = display_sympy_value(compiled).strip()
    if not answer:
        raise UnusableVariant("the answer recipe renders an empty answer")

    distractor_choices: list[str] = []
    # The key counts as a choice, so a distractor equal to it in value is rejected.
    seen: list[object] = [compiled]
    for distractor in body.distractors:
        value = compile_distractor_value(body, distractor, values)
        if any(same_value(value, other) for other in seen):
            raise UnusableVariant("distractor choices are not distinct")
        seen.append(value)
        display = display_sympy_value(value).strip()
        if not display or display == answer or display in distractor_choices:
            raise UnusableVariant("distractor choices are not distinct")
        distractor_choices.append(display)
    if not distractor_choices:
        raise UnusableVariant("the template declares no distractors")
    choices = list(distractor_choices)
    correct_index = seeded_index(
        validated.template.template_id, seed, "correct-index", len(choices) + 1
    )
    choices.insert(correct_index, answer)
    return MathQuestionInstance(
        template_id=validated.template.template_id,
        artifact_id=validated.artifact_id,
        seed=seed,
        parameters={name: fraction_text(value) for name, value in values.items()},
        equation=render_goal_display(body, values),
        question=render_item_text(body, values),
        choices=choices,
        correct_index=correct_index,
        answer=answer,
        topic=template.topic,
    )
