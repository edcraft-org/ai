"""Domain-neutral contracts for NL-fidelity verification.

The engine never interprets a domain artifact. A plugin owns the artifact type,
the blind parse-back request, the anchor rules and the equivalence relation.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.usage import ModelUsageSummary

FidelityStatus = Literal["passed", "failed", "inconclusive"]
EvidenceStrength = Literal["deterministic", "probabilistic"]


class FidelityRecord(BaseModel):
    """Shared strictness for report records that cross the application boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CanonicalArtifact(FidelityRecord):
    """A deterministic, comparable projection of one domain artifact."""

    domain: str = Field(min_length=1)
    payload: dict[str, Any]
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FidelityVerdict(FidelityRecord):
    """The tri-state outcome of one deterministic or plugin-owned check."""

    status: FidelityStatus
    reasons: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"


class FidelityReport(FidelityRecord):
    """One fidelity attempt, including the parse-back evidence and any errors."""

    status: FidelityStatus
    domain: str = Field(min_length=1)
    reconstruction: dict[str, Any] | None = None
    verdict: FidelityVerdict
    prompt_version: str
    request_sha256: str
    cached: bool = False
    error_code: str | None = None
    evidence_strength: EvidenceStrength | None = None
    provider: str | None = None
    model: str | None = None
    usage: ModelUsageSummary = Field(default_factory=ModelUsageSummary)


class FidelityPlugin(Protocol):
    """A domain's blind parse-back, canonicalization and equivalence policy."""

    domain: str
    artifact_model: type[BaseModel]
    evidence_strength: EvidenceStrength

    def requires_check(self, artifact: BaseModel) -> bool:
        """Return whether free text needs blind parse-back at all."""
        ...

    def reconstruction_request(self, text: str) -> StructuredGenerationRequest[Any]:
        """Build one request that must not reveal the expected artifact."""
        ...

    def canonicalize(self, artifact: BaseModel) -> CanonicalArtifact:
        """Project the artifact to comparable data and a stable digest."""
        ...

    def check_anchors(self, artifact: BaseModel, text: str) -> FidelityVerdict:
        """Check structural text anchors before any model call."""
        ...

    def equivalent(
        self, expected: BaseModel, reconstructed: BaseModel
    ) -> FidelityVerdict:
        """Compare a blind parse to the expected artifact conservatively."""
        ...
