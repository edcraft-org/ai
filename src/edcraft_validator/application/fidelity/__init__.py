"""Domain-neutral NL-fidelity gate with per-domain plugins."""

from edcraft_validator.application.fidelity.contracts import (
    CanonicalArtifact,
    EvidenceStrength,
    FidelityPlugin,
    FidelityReport,
    FidelityStatus,
    FidelityVerdict,
)
from edcraft_validator.application.fidelity.engine import (
    DEFAULT_CACHE_SIZE,
    FidelityCache,
    default_cache,
    verify_text_fidelity,
)

__all__ = [
    "DEFAULT_CACHE_SIZE",
    "CanonicalArtifact",
    "EvidenceStrength",
    "FidelityCache",
    "FidelityPlugin",
    "FidelityReport",
    "FidelityStatus",
    "FidelityVerdict",
    "default_cache",
    "verify_text_fidelity",
]
