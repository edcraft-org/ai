"""Deterministic expansion of approved code-question templates."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from string import Formatter

from edcraft_validator.models import GeneratedQuestion

from .expressions import SafeExpression
from .models import (
    ApprovedCodeQuestionTemplate,
    ParameterValue,
    TemplateQuestionInstance,
    TemplateValidationError,
    _case_count,
)


def generate_template_instance(
    approved: ApprovedCodeQuestionTemplate, seed: int
) -> TemplateQuestionInstance:
    """Expand an approved template without AI calls or per-instance validation."""
    template = approved.template
    if approved.validation.cases_validated != _case_count(template):
        raise ValueError("approved template does not cover its complete input domain")
    cases = approved.validation.validated_cases
    expected_inputs = [
        dict(
            zip(
                (parameter.name for parameter in template.parameters),
                values,
                strict=True,
            )
        )
        for values in itertools.product(
            *(parameter.values for parameter in template.parameters)
        )
    ]
    answers_by_inputs = {_case_key(case.inputs): case.answer for case in cases}
    if len(answers_by_inputs) != len(cases) or set(answers_by_inputs) != {
        _case_key(inputs) for inputs in expected_inputs
    }:
        raise ValueError("approved template does not cover its complete input domain")

    inputs = {
        parameter.name: copy.deepcopy(
            _seeded_choice(parameter.values, template.template_id, seed, parameter.name)
        )
        for parameter in template.parameters
    }
    names = tuple(inputs)
    answer = copy.deepcopy(answers_by_inputs[_case_key(inputs)])
    distractors = [
        SafeExpression(recipe.expression, names).evaluate(inputs)
        for recipe in template.distractors
    ]
    distractor_reasons = [
        render_template(recipe.reason_template, inputs)
        for recipe in template.distractors
    ]
    question = GeneratedQuestion(
        code=template.code,
        entry_function=template.entry_function,
        inputs=inputs,
        question=render_template(template.question_template, inputs, require_all=True),
        proposed_answer=answer,
        distractors=distractors,
        distractor_reasons=distractor_reasons,
        answer_target=template.answer_target,
        question_type=template.question_type,
    )
    return TemplateQuestionInstance(
        template_id=template.template_id,
        seed=seed,
        parameters=inputs,
        question=question,
    )


def render_template(
    source: str, values: dict[str, ParameterValue], *, require_all: bool = False
) -> str:
    fields: set[str] = set()
    try:
        parsed = list(Formatter().parse(source))
    except ValueError as exc:
        raise TemplateValidationError(f"invalid text template: {exc}") from exc
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if field_name not in values:
            raise TemplateValidationError(
                f"text template uses unknown parameter {field_name!r}"
            )
        if format_spec or conversion:
            raise TemplateValidationError(
                "text templates do not support conversions or format specifications"
            )
        fields.add(field_name)
    if require_all and fields != set(values):
        raise TemplateValidationError(
            "question_template placeholders must exactly match the parameters"
        )
    rendered = source.format_map(values)
    if not rendered.strip():
        raise TemplateValidationError("rendered text must not be blank")
    return rendered


def _case_key(inputs: dict[str, ParameterValue]) -> str:
    return json.dumps(inputs, sort_keys=True, separators=(",", ":"))


def _seeded_choice(
    values: list[ParameterValue], digest: str, seed: int, name: str
) -> ParameterValue:
    payload = f"{digest}:{seed}:{name}".encode()
    index = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % len(values)
    return values[index]
