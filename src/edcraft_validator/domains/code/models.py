"""Code-domain authoring inputs."""

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.domains.code.capabilities import Difficulty, ProgrammingTopic


class CodeTemplateAuthoringRequest(BaseModel):
    """Human-selected constraints for one code template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    topic: ProgrammingTopic
    difficulty: Difficulty
    num_distractors: int = Field(default=3, ge=2, le=3)
