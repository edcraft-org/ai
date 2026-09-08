from typing import Any, Literal

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


class TemplatePromptMetadata(BaseModel):
    """Versioned identity of the exact messages sent to a provider."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TemplateAuthoringProvenance(BaseModel):
    """Non-secret evidence for reproducing one successful authoring attempt."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    prompt: TemplatePromptMetadata
    request: dict[str, Any]
    generation_duration_ms: float = Field(ge=0)
    validation_duration_ms: float = Field(ge=0)
    status: Literal["approved"] = "approved"
