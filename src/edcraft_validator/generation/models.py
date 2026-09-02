from pydantic import BaseModel, ConfigDict, Field, field_validator

from edcraft_validator.domains.code.capabilities import Difficulty, ProgrammingTopic


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


class TemplateAuthoringRequest(BaseModel):
    """Human-selected constraints for one reusable template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    topic: ProgrammingTopic
    difficulty: Difficulty
    num_distractors: int = Field(default=3, ge=2, le=3)
