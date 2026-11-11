"""Render and validate placeholders in question and explanation text."""

from __future__ import annotations

from edcraft_validator.domains.code.code_schemas import (
    TemplateValidationError,
)
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.text_templates import template_fields


def render_template(
    source: str, values: dict[str, ParameterValue], *, require_all: bool = False
) -> str:
    try:
        fields = template_fields(source)
    except ValueError as exc:
        raise TemplateValidationError(str(exc)) from exc
    for field_name in fields:
        if field_name not in values:
            raise TemplateValidationError(
                f"text template uses unknown parameter {field_name!r}"
            )
    if require_all and fields != set(values):
        raise TemplateValidationError(
            "question_template placeholders must exactly match the parameters"
        )
    rendered = source.format_map(values)
    if not rendered.strip():
        raise TemplateValidationError("rendered text must not be blank")
    return rendered
