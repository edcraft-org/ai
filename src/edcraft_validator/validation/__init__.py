"""Structured evidence for domain-specific template approval."""

from edcraft_validator.validation.contracts import (
    AssuranceLevel,
    EvidenceStatus,
    ValidationEvidence,
    ValidationFailure,
)
from edcraft_validator.validation.pipeline import ValidationPipeline

__all__ = [
    "AssuranceLevel",
    "EvidenceStatus",
    "ValidationEvidence",
    "ValidationFailure",
    "ValidationPipeline",
]
