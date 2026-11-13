"""Helpers shared by domain modules without coupling them to each other."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationEvidence


class ReviewTemplateView(BaseModel):
    """Domain-owned projection of a validated artifact for human review."""

    template_id: str
    candidate: dict[str, Any]
    language: str | None = None
    limits: dict[str, Any] | None = None


def build_review_view(
    artifact: ValidatedTemplateArtifact, *, language: str | None
) -> ReviewTemplateView | None:
    """Project the shared review fields without exposing artifact internals."""
    template = getattr(artifact, "template", None)
    template_id = getattr(template, "template_id", None)
    dump = getattr(template, "model_dump", None)
    if not isinstance(template_id, str) or dump is None:
        return None
    validation = getattr(artifact, "validation", None)
    return ReviewTemplateView(
        template_id=template_id,
        candidate=dump(mode="json"),
        language=language,
        limits=validation.model_dump() if validation is not None else None,
    )


def content_sha256(model: BaseModel) -> str:
    """Identify exact canonical content independently of any assessment."""
    return hashlib.sha256(
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


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
    recorded_sha256 = item.details.get("subject_sha256")
    if recorded_sha256 is None:
        recorded_sha256 = item.details.get("template_sha256")
    if recorded_sha256 is None:
        details.update(
            unavailable=True,
            unavailable_reason="Assessment evidence is missing its subject identity",
        )
        status = "incomplete"
    elif recorded_sha256 != expected_sha256:
        details.update(
            unavailable=True,
            unavailable_reason="Assessment evidence belongs to a different subject",
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
