"""Deterministically expand validated math templates into questions."""

from __future__ import annotations

import hashlib
from fractions import Fraction

from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.instantiate import (
    compile_distractor_value,
    display_sympy_value,
    fraction_text,
    parameter_combinations,
    render_goal_display,
    render_item_text,
)
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from edcraft_validator.domains.math.ir.solve import SolveUnavailable, solve_item
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    ValidatedMathTemplate,
    render_linear_equation,
    render_math_text,
)
from edcraft_validator.domains.math.math_schemas import (
    parameter_combinations as legacy_parameter_combinations,
)
from edcraft_validator.domains.math.safe_linear import (
    evaluate_expression,
    format_fraction,
)
from edcraft_validator.domains.math.validation.primitives import option_equivalent


class UnusableVariant(ValueError):
    """One parameter combination cannot yield a sound question."""


def generate_math_question(
    validated: ValidatedMathTemplate, seed: int
) -> MathQuestionInstance:
    """Expand one validated template without AI calls or external I/O."""
    template = validated.template
    if template.item is not None:
        return _generate_ir_question(validated, template.item, seed)
    combinations = legacy_parameter_combinations(template.parameters or [])
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
    if (
        template.answer_expression is None
        or template.question_template is None
        or template.distractors is None
    ):
        raise ValueError("legacy templates require linear authoring fields")
    answer_value = evaluate_expression(template.answer_expression, values)
    answer = format_fraction(answer_value)
    # The equation template is validated to the canonical a*x + b = c shape, so
    # render it with correct signs instead of raw placeholder substitution.
    equation = render_linear_equation(values["a"], values["b"], values["c"])
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
    parameters: dict[str, int | str] = dict(values)
    return MathQuestionInstance(
        template_id=template.template_id,
        artifact_id=validated.artifact_id,
        seed=seed,
        parameters=parameters,
        equation=equation,
        question=question,
        choices=choices,
        correct_index=correct_index,
        answer=answer,
    )


def _generate_ir_question(
    validated: ValidatedMathTemplate,
    template: MathTemplateSpec,
    seed: int,
) -> MathQuestionInstance:
    combinations = parameter_combinations(template)
    if not combinations:
        raise ValueError("validated template has an empty parameter domain")
    start = _seeded_index(
        validated.template.template_id, seed, "parameter-combination", len(combinations)
    )
    for offset in range(len(combinations)):
        values = combinations[(start + offset) % len(combinations)]
        try:
            return _build_ir_instance(validated, template, seed, values)
        except (MathCompileError, SolveUnavailable, UnusableVariant):
            continue
    raise ValueError("Could not produce a usable question from this template")


def _build_ir_instance(
    validated: ValidatedMathTemplate,
    template: MathTemplateSpec,
    seed: int,
    values: dict[str, Fraction],
) -> MathQuestionInstance:
    body = template.body
    solved = solve_item(body, values)
    answer = solved.answer.display.replace("**", "^").strip()
    if not answer:
        raise UnusableVariant("the solver returned an empty display answer")
    distractor_choices: list[str] = []
    for distractor in body.distractors:
        value = compile_distractor_value(body, distractor, values)
        if _matches_key(value, solved.value) is not False:
            raise UnusableVariant("a distractor is not demonstrably different")
        display = display_sympy_value(value).strip()
        if not display or display == answer or display in distractor_choices:
            raise UnusableVariant("distractor choices are not distinct")
        distractor_choices.append(display)
    if not distractor_choices:
        raise UnusableVariant("the template declares no distractors")
    choices = list(distractor_choices)
    correct_index = _seeded_index(
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


def _matches_key(value: object, key: object) -> bool | None:
    """Return True/False when decided, or None when no proof is available."""
    status = option_equivalent(value, key).status
    if status == "passed":
        return True
    if status == "failed":
        return False
    return None


def _seeded_index(template_id: str, seed: int, name: str, size: int) -> int:
    payload = f"{template_id}:{seed}:{name}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % size
