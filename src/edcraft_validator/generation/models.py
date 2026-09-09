from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TemplateProviderSelection(BaseModel):
    """Provider and optional model selected for one authoring request."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)

    @field_validator("provider", "model")
    @classmethod
    def strip_non_blank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TemplateAuthoringProvenance(BaseModel):
    """Non-secret trace of one successful model authoring attempt."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    base_prompt_version: str = Field(min_length=1)
    request: dict[str, Any]
    generated_at: datetime
    generation_duration_ms: float = Field(ge=0)


class ValidatedTemplateArtifact(BaseModel):
    """Shared contract for every domain's technically validated artifact."""

    authoring: TemplateAuthoringProvenance | None = None
