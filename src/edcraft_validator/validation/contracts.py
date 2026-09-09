"""Structured evidence shared by domain-specific template validators."""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.models import ValidationIssue

EvidenceStatus = Literal["passed", "failed"]
AssuranceLevel = Literal["proof", "exhaustive", "bounded", "sampled", "heuristic"]


class ValidationFailure(ValueError):
    """A domain-independent validation failure with structured context."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "VALIDATION_FAILED",
        field: str | None = None,
        context: dict[str, Any] | None = None,
        evidence: list[ValidationEvidence] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.context = copy.deepcopy(context or {})
        self.evidence = copy.deepcopy(evidence or [])


class ValidationEvidence(BaseModel):
    """Result of one explainable check performed during template validation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    check: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    status: EvidenceStatus
    assurance: AssuranceLevel
    issues: list[ValidationIssue] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(default=0, ge=0)
