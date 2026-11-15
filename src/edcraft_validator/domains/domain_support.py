"""Helpers shared by domain modules without coupling them to each other."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domain_types import (
    DEFAULT_DISTRACTORS,
    MAX_DISTRACTORS,
    MIN_DISTRACTORS,
    Difficulty,
)
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationEvidence

MAX_PROMPT_LENGTH = 4000


class TemplateRequest(BaseModel):
    """Free-form authoring request shared by every domain."""

    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    difficulty: Difficulty
    num_distractors: int = Field(
        default=DEFAULT_DISTRACTORS, ge=MIN_DISTRACTORS, le=MAX_DISTRACTORS
    )

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


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


def build_template_id(
    domain_name: str, request: TemplateRequest, proposal: BaseModel
) -> str:
    """Derive a stable template id from the request and the model proposal."""
    identity_payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    digest = hashlib.sha256(identity_payload).hexdigest()[:12]
    return f"{domain_name}.{request.difficulty}.{digest}"


def seeded_index(key: str, seed: int, name: str, size: int) -> int:
    """Pick a reproducible index so seeded generation needs no random state."""
    payload = f"{key}:{seed}:{name}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % size


def require_checked(
    evidence: list[ToolEvidence],
    *,
    required: frozenset[str],
    advisory_checks: frozenset[str],
) -> None:
    """Refuse packaging unless every blocking check passed and none is missing."""
    if not evidence or any(
        item.status != "passed" and item.tool not in advisory_checks
        for item in evidence
    ):
        raise ValueError("All selected checks must pass")

    passed = {item.tool for item in evidence if item.status == "passed"}
    missing = sorted(required - passed)
    if missing:
        raise ValueError("Missing passing required checks: " + ", ".join(missing))


def require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    """Narrow a protocol argument to the domain's concrete model."""
    if not isinstance(value, model):
        raise TypeError(f"domain requires {model.__name__}")
    return value


def save_checked_evidence(
    item: ToolEvidence,
    expected_sha256: str,
    *,
    advisory_checks: frozenset[str],
) -> ValidationEvidence:
    """Keep technical passes and advisory verdicts distinct in saved evidence."""
    if item.tool not in advisory_checks:
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
        # Evidence written before the key was standardised.
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

    # Saved artifacts identify advisory rows by this flag, so it is set here
    # from application policy and never taken from the tool's own details.
    details["advisory"] = True
    return ValidationEvidence(
        check=item.tool,
        status=status,
        duration_ms=item.duration_ms,
        issues=[finding.model_dump() for finding in item.findings],
        details=details,
    )
