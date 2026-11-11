"""Helpers shared by domain modules without coupling them to each other."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationEvidence


def require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    """Narrow a protocol argument to the domain's concrete model."""
    if not isinstance(value, model):
        raise TypeError(f"domain requires {model.__name__}")
    return value


def save_checked_evidence(
    item: ToolEvidence,
    expected_sha256: str,
    *,
    advisory_names: frozenset[str],
) -> ValidationEvidence:
    """Keep technical passes and advisory verdicts distinct in saved evidence."""
    if item.tool not in advisory_names:
        return ValidationEvidence(
            check=item.tool,
            status="passed",
            duration_ms=item.duration_ms,
            issues=[finding.model_dump() for finding in item.findings],
            details={"tool_version": item.version},
        )
    details: dict[str, Any] = {"tool_version": item.version, **item.details}
    recorded_sha256 = item.details.get("template_sha256")
    if recorded_sha256 is None:
        details.update(
            unavailable=True,
            unavailable_reason="Assessment evidence is missing its template identity",
        )
        status = "incomplete"
    elif recorded_sha256 != expected_sha256:
        details.update(
            unavailable=True,
            unavailable_reason="Assessment evidence belongs to a different template",
        )
        status = "incomplete"
    elif item.status == "failed":
        status = "failed"
    elif item.status == "error":
        details.update(
            unavailable=True,
            unavailable_reason="Advisory assessment did not return a verdict",
        )
        status = "incomplete"
    else:
        status = "passed"
    return ValidationEvidence(
        check=item.tool,
        status=status,
        duration_ms=item.duration_ms,
        issues=[finding.model_dump() for finding in item.findings],
        details=details,
    )
