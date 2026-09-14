"""Structured evidence for domain-specific template validation."""

from edcraft_validator.validation.contracts import (
    AssuranceLevel,
    CheckResult,
    EvidenceStatus,
    ValidationCheck,
    ValidationEvidence,
    ValidationFailure,
    ValidationPlan,
    ValidationPolicy,
    ValidationReport,
)
from edcraft_validator.validation.pipeline import ValidationPipeline

__all__ = [
    "AssuranceLevel",
    "ValidationReport",
    "ValidationPolicy",
    "ValidationPlan",
    "ValidationCheck",
    "CheckResult",
    "EvidenceStatus",
    "ValidationEvidence",
    "ValidationFailure",
    "ValidationPipeline",
]
