"""Structured evidence for domain-specific template validation."""

from edcraft_validator.validation.check_runner import ValidationPipeline
from edcraft_validator.validation.validation_contracts import (
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
