"""Parse named placeholders in authoring text templates.

Both domains reject positional fields, conversions and format specifications
before rendering. Keeping the parser here stops the two copies from drifting.
"""

from __future__ import annotations

from collections.abc import Mapping
from string import Formatter
from typing import Any


def template_fields(source: str) -> set[str]:
    """Return named placeholder fields, rejecting unsupported syntax."""
    try:
        parsed = list(Formatter().parse(source))
    except ValueError as exc:
        raise ValueError(f"invalid text template: {exc}") from exc
    fields: set[str] = set()
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if not field_name:
            raise ValueError("text templates require named placeholders")
        if format_spec or conversion:
            raise ValueError(
                "text templates do not support conversions or format specifications"
            )
        fields.add(field_name)
    return fields


def render_text_template(
    source: str,
    values: Mapping[str, Any],
    *,
    require_all: bool = False,
) -> str:
    """Render a template after checking every placeholder has a value."""
    fields = template_fields(source)
    missing = fields - set(values)
    if missing:
        raise ValueError(
            "text template uses unknown placeholders: " + ", ".join(sorted(missing))
        )
    if require_all and fields != set(values):
        raise ValueError("template placeholders must exactly match the values")
    rendered = source.format_map(values)
    if not rendered.strip():
        raise ValueError("rendered text must not be blank")
    return rendered
