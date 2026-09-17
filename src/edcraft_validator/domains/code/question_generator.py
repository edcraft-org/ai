"""Deterministically expand validated code templates into questions."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json

from edcraft_validator.domains.code.code_schemas import (
    CodeQuestionInstance,
    GeneratedQuestion,
    ValidatedCodeTemplate,
    _case_count,
)
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.domains.code.text_rendering import render_template


def generate_code_question(
    validated: ValidatedCodeTemplate, seed: int
) -> CodeQuestionInstance:
    """Expand a validated template without AI calls or per-instance validation."""
    template = validated.template
    if validated.validation.cases_validated != _case_count(template):
        raise ValueError("validated template does not cover its complete input domain")
    cases = validated.validation.validated_cases
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
        raise ValueError("validated template does not cover its complete input domain")

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
    return CodeQuestionInstance(
        template_id=template.template_id,
        seed=seed,
        parameters=inputs,
        question=question,
    )


def _case_key(inputs: dict[str, ParameterValue]) -> str:
    return json.dumps(inputs, sort_keys=True, separators=(",", ":"))


def _seeded_choice(
    values: list[ParameterValue], digest: str, seed: int, name: str
) -> ParameterValue:
    payload = f"{digest}:{seed}:{name}".encode()
    index = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % len(values)
    return values[index]
