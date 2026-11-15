"""Deterministically expand approved math templates into seeded questions.

Generation evaluates the approved recipes and renders them without model, MCP
or external calls. It rejects unusable option combinations such as repeated
choices. Correctness, and form where the goal
requires it, were checked during authoring.
"""

from __future__ import annotations

from fractions import Fraction

import sympy

from edcraft_validator.domains.domain_support import seeded_index
from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.instantiate import (
    compile_distractor_value,
    display_sympy_value,
    fraction_text,
    render_goal_display,
    render_goal_display_latex,
    render_item_segments,
    render_item_text,
    sample_parameter_combinations,
)
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    QuestionSegment,
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

    distractor_values: list[object] = []
    # The key counts as a choice, so a distractor equal to it in value is rejected.
    seen: list[object] = [compiled]
    for distractor in body.distractors:
        value = compile_distractor_value(body, distractor, values)
        if any(same_value(value, other) for other in seen):
            raise UnusableVariant("distractor choices are not distinct")
        seen.append(value)
        distractor_values.append(value)
    if not distractor_values:
        raise UnusableVariant("the template declares no distractors")

    answer, distractor_choices = _render_choices(compiled, distractor_values)
    if not answer:
        raise UnusableVariant("the answer recipe renders an empty answer")
    rendered_choices: list[str] = [answer]
    for display in distractor_choices:
        if not display or display in rendered_choices:
            raise UnusableVariant("distractor choices are not distinct")
        rendered_choices.append(display)

    choices = list(distractor_choices)
    correct_index = seeded_index(
        validated.template.template_id, seed, "correct-index", len(choices) + 1
    )
    choices.insert(correct_index, answer)

    answer_latex, distractor_choices_latex = _render_choices_latex(
        compiled, distractor_values
    )
    choices_latex = list(distractor_choices_latex)
    choices_latex.insert(correct_index, answer_latex)

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
        equation_latex=render_goal_display_latex(body, values),
        choices_latex=choices_latex,
        answer_latex=answer_latex,
        question_segments=[
            QuestionSegment(kind=kind, value=value)
            for kind, value in render_item_segments(body, values)
        ],
    )


def _render_choices(key: object, distractors: list[object]) -> tuple[str, list[str]]:
    """Render the key and distractors with one consistent set form.

    A one-element set and a plain scalar are both shown bare, so a lone root
    never stands out with braces. If that does not describe every choice and
    the key is a set, every choice is shown as a set and scalar distractors are
    wrapped as one-element sets. Other keys keep the existing rendering.
    """
    values = [key, *distractors]
    if all(_is_bare_choice(value) for value in values):
        rendered = [_render_bare_choice(value) for value in values]
    elif isinstance(key, sympy.FiniteSet):
        rendered = [_render_set_choice(value) for value in values]
    else:
        rendered = [display_sympy_value(value).strip() for value in values]
    return rendered[0], rendered[1:]


def _is_bare_choice(value: object) -> bool:
    """Whether a choice is a scalar or a one-element set that can show bare."""
    if isinstance(value, sympy.FiniteSet):
        return len(value.args) == 1
    return not isinstance(value, sympy.Set)


def _render_bare_choice(value: object) -> str:
    """Render a scalar directly, or a one-element set as its element."""
    if isinstance(value, sympy.FiniteSet):
        return display_sympy_value(next(iter(value.args))).strip()
    return display_sympy_value(value).strip()


def _render_set_choice(value: object) -> str:
    """Render a set directly, or wrap a scalar as a one-element set."""
    if isinstance(value, sympy.FiniteSet):
        return display_sympy_value(value).strip()
    return display_sympy_value(sympy.FiniteSet(value)).strip()


def _render_choices_latex(
    key: object, distractors: list[object]
) -> tuple[str, list[str]]:
    """Typeset the key and distractors with the same set rule as plain choices."""
    values = [key, *distractors]
    if all(_is_bare_choice(value) for value in values):
        rendered = [_render_bare_choice_latex(value) for value in values]
    elif isinstance(key, sympy.FiniteSet):
        rendered = [_render_set_choice_latex(value) for value in values]
    else:
        rendered = [sympy.latex(value) for value in values]
    return rendered[0], rendered[1:]


def _render_bare_choice_latex(value: object) -> str:
    """Typeset a scalar directly, or a one-element set as its element."""
    if isinstance(value, sympy.FiniteSet):
        return sympy.latex(next(iter(value.args)))
    return sympy.latex(value)


def _render_set_choice_latex(value: object) -> str:
    """Typeset a set directly, or wrap a scalar as a one-element set."""
    if isinstance(value, sympy.FiniteSet):
        return sympy.latex(value)
    return sympy.latex(sympy.FiniteSet(value))
