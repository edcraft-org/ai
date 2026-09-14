"""Structured evidence shared by domain-specific template validators."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.models import ValidationIssue

EvidenceStatus = Literal["passed", "failed", "incomplete"]
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


@dataclass
class CheckResult:
    """A check's findings; the runner adds its identity and elapsed time."""

    status: EvidenceStatus = "passed"
    issues: list[ValidationIssue] = dataclass_field(default_factory=list)
    details: dict[str, Any] = dataclass_field(default_factory=dict)
    failure: ValidationFailure | None = None


class ValidationCheck[ContextT](Protocol):
    name: str
    assurance: AssuranceLevel

    def run(self, context: ContextT) -> CheckResult | None:
        """Return None only when the check does not apply to this context."""
        ...


@dataclass(frozen=True)
class ValidationPolicy:
    """Required checks must pass; by default any failure stops later checks."""

    required_checks: frozenset[str]
    stop_on_failure: bool = True


@dataclass
class ValidationReport:
    evidence: list[ValidationEvidence]
    policy: ValidationPolicy
    failure: ValidationFailure | None = None

    @property
    def missing_checks(self) -> frozenset[str]:
        return self.policy.required_checks - {item.check for item in self.evidence}

    @property
    def accepted(self) -> bool:
        passed = {item.check for item in self.evidence if item.status == "passed"}
        return self.failure is None and self.policy.required_checks <= passed

    def raise_for_failure(self) -> None:
        if self.accepted:
            return
        failure = self.failure or ValidationFailure(
            "Required validation checks did not all pass",
            code="VALIDATION_INCOMPLETE",
            context={"missing_checks": sorted(self.missing_checks)},
        )
        failure.evidence = copy.deepcopy(self.evidence)
        raise failure
