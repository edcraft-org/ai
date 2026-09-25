"""Validated artifacts and provenance shared by all domains."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.llm.llm_contracts import RecommendedCheck


class TemplateAuthoringProvenance(BaseModel):
    """Non-secret trace of one successful model authoring attempt."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    base_prompt_version: str = Field(min_length=1)
    request: dict[str, Any]
    recommended_checks: list[RecommendedCheck] = Field(default_factory=list)
    generated_at: datetime
    generation_duration_ms: float = Field(ge=0)


class ValidatedTemplateArtifact(BaseModel):
    """Shared contract for every domain's technically validated artifact."""

    authoring: TemplateAuthoringProvenance | None = None
