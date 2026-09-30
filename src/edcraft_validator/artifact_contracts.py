"""Validated artifacts and provenance shared by all domains."""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.llm.llm_contracts import RecommendedCheck


class TemplateAuthoringProvenance(BaseModel):
    """Non-secret record of a completed checking job, including failed attempts."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider_settings: dict[str, Any]
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    base_prompt_version: str = Field(min_length=1)
    request: dict[str, Any]
    proposal: dict[str, Any]
    fixed_plan: list[str] = Field(min_length=1)
    generation_messages: list[dict[str, Any]]
    response_schema: dict[str, Any]
    recommended_checks: list[RecommendedCheck] = Field(default_factory=list)
    tool_catalogue: list[dict[str, Any]] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime
    generation_duration_ms: float = Field(ge=0)


class ValidatedTemplateArtifact(BaseModel):
    """Shared contract for every domain's technically validated artifact."""

    artifact_schema_version: Literal[1] = 1
    # Domain finalization creates an intermediate artifact; the application seals
    # its complete authoring record once all provenance is available.
    artifact_id: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    authoring: TemplateAuthoringProvenance | None = None

    def with_authoring(self, provenance: TemplateAuthoringProvenance) -> Self:
        """Identify the exact saved record, without changing template semantics.

        Timings and call IDs belong to this record too: a fresh checking run may
        receive a new identity even if its proposal is unchanged. This is a record
        identifier, not an approval or a tamper-verification mechanism.
        """
        artifact = self.model_copy(update={"authoring": provenance})
        payload = json.dumps(
            artifact.model_dump(mode="json", exclude={"artifact_id"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        return artifact.model_copy(
            update={"artifact_id": "sha256:" + hashlib.sha256(payload).hexdigest()}
        )
