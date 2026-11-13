"""Bounded repair for provider schema rejections during authoring."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError, model_validator
from test_check_pilot_application import (
    app,
    author,
    valid_check_proposal,
    valid_plan,
    valid_template_proposal,
)

from edcraft_validator.llm.llm_errors import GenerationSchemaError

ROLE_LIMITS = {
    "check-planner": 3,
    "check-author": 3,
    "template-author": 3,
}
STAGE_PHRASE = {
    "check-planner": "exact kernel goal fields",
    "check-author": "registered operation",
    "template-author": "structured_family",
}


class _RejectedFamily(BaseModel):
    value: int

    @model_validator(mode="after")
    def reject_binding(self):
        raise ValueError(
            "binding path 'expression.args.0.num' does not address a numeric leaf"
        )


def _caused_schema_error() -> GenerationSchemaError:
    """Schema rejection carrying the local validator's field detail."""
    try:
        _RejectedFamily(value=1)
    except ValidationError as cause:
        error = GenerationSchemaError("SECRET provider payload")
        error.__cause__ = cause
        return error
    raise AssertionError("the sample model must reject")


class SchemaErrorProvider:
    """Fail a chosen authoring role with a schema error before succeeding."""

    provider = "stub"
    model = "stub-schema-error"

    def __init__(self, role: str, *, errors: int, with_cause: bool = False) -> None:
        self.role = role
        self.errors = errors
        self.with_cause = with_cause
        self.calls: list[dict] = []

    def generation_settings(self):
        return {"mode": "scripted", "reasoning_effort": "none"}

    def generate(self, request):
        if request.prompt_version.startswith("check-planner"):
            role = "check-planner"
            proposal = valid_plan()
        elif request.prompt_version.startswith("check-author"):
            role = "check-author"
            proposal = valid_check_proposal()
        else:
            role = "template-author"
            proposal = valid_template_proposal()
        self.calls.append(
            {
                "role": role,
                "schema": request.schema_name,
                "messages": request.messages,
            }
        )
        if role == self.role and self.errors:
            self.errors -= 1
            if self.with_cause:
                raise _caused_schema_error()
            raise GenerationSchemaError("SECRET raw provider payload")
        return proposal


def feedback_texts(provider: SchemaErrorProvider, role: str) -> list[str]:
    return [
        call["messages"][1]["content"]
        for call in provider.calls
        if call["role"] == role
    ]


@pytest.mark.parametrize("role", list(ROLE_LIMITS))
def test_schema_error_is_repaired_with_bounded_feedback(
    tmp_path: Path, role: str
) -> None:
    provider = SchemaErrorProvider(role, errors=1)
    application = app(tmp_path)

    record = author(application, provider)

    assert record.status == "ready", record.findings
    assert record.check is not None
    assert record.template is not None
    assert [call["role"] for call in provider.calls].count(role) == 2
    retry_feedback = feedback_texts(provider, role)[1]
    assert "closed schema" in retry_feedback
    assert STAGE_PHRASE[role] in retry_feedback
    assert "SECRET" not in retry_feedback
    assert len(application.list_checks("owner")) == 1


@pytest.mark.parametrize("role", list(ROLE_LIMITS))
def test_schema_error_repair_exhaustion_stores_no_invalid_data(
    tmp_path: Path, role: str
) -> None:
    provider = SchemaErrorProvider(role, errors=10_000)
    application = app(tmp_path)

    record = author(application, provider)

    assert record.status == "error"
    assert record.findings
    assert [call["role"] for call in provider.calls].count(role) == ROLE_LIMITS[role]
    if role in {"check-planner", "check-author"}:
        assert application.list_checks("owner") == []
        assert record.check is None
        assert record.template is None
    else:
        # The check was validly authored and qualified before the template role.
        assert len(application.list_checks("owner")) == 1
        assert record.check is not None
        assert record.template is None
        assert record.qualification is None


def test_schema_error_feedback_repeats_local_field_details_without_raw_input(
    tmp_path: Path,
) -> None:
    provider = SchemaErrorProvider("template-author", errors=1, with_cause=True)
    application = app(tmp_path)

    record = author(application, provider)

    assert record.status == "ready", record.findings
    retry_feedback = feedback_texts(provider, "template-author")[1]
    assert "closed schema" in retry_feedback
    assert "binding path" in retry_feedback
    assert "does not address a numeric leaf" in retry_feedback
    assert "SECRET" not in retry_feedback
    assert "input_value" not in retry_feedback
