"""Bounded answer/option checks shared by sampled validation and draft generation."""

import json
from typing import Any

from edcraft_validator.domains.code.code_schemas import TemplateValidationError
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.value_comparison import equivalent, same_value_shape


def validate_supported_answer(inputs: dict[str, ParameterValue], answer: Any) -> None:
    valid = type(answer) in {int, float, str} or (
        type(answer) is list and all(type(item) is int for item in answer)
    )
    if not valid:
        raise TemplateValidationError(
            "answers must be numbers, strings, or integer lists; "
            f"received {type(answer).__name__} for inputs {inputs}",
            code="ANSWER_TYPE_UNSUPPORTED",
            field="answer_expression",
            inputs=inputs,
        )


def require_json_value(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TemplateValidationError(f"{label} is not a finite JSON value") from exc


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
    _validate_distractor_type(inputs, answer, distractor, index)
    if equivalent(distractor, answer):
        raise TemplateValidationError(
            f"distractor {index} equals the answer for inputs {inputs}",
            code="DISTRACTOR_EQUALS_ANSWER",
            field=f"distractors.{index}",
            inputs=inputs,
        )


def _validate_distractor_type(inputs, answer, distractor, index):
    require_json_value(distractor, f"distractor {index}")
    if not same_value_shape(distractor, answer):
        raise TemplateValidationError(
            f"distractor {index} has the wrong type for inputs {inputs}",
            code="DISTRACTOR_TYPE_MISMATCH",
            field=f"distractors.{index}",
            inputs=inputs,
        )
