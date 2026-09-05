"""Structured evidence shared by domain-specific template validators."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.models import ValidationIssue

EvidenceStatus = Literal["passed", "failed"]
AssuranceLevel = Literal["proof", "exhaustive", "bounded", "sampled", "heuristic"]


class ValidationEvidence(BaseModel):
    """Result of one explainable check performed during template approval."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    check: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    status: EvidenceStatus
    assurance: AssuranceLevel
    issues: list[ValidationIssue] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(default=0, ge=0)
