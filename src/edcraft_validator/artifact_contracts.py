"""Validated artifacts and provenance shared by all domains."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    tool_catalogue: list[dict[str, Any]] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime
    generation_duration_ms: float = Field(ge=0)


class ValidatedTemplateArtifact(BaseModel):
    """Shared contract for every domain's technically validated artifact."""

    # Assigned when a complete checking run creates the reusable artifact.
    artifact_id: str | None = None
    authoring: TemplateAuthoringProvenance | None = None
