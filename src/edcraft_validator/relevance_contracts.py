"""Domain-independent inputs and evidence for text relevance measurement."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from edcraft_validator.llm.embeddings import SimilarityReport

NonemptyText = Annotated[str, StringConstraints(min_length=1, max_length=200_000)]


class RelevanceInput(BaseModel):
    """A caller's complete textual representation, with its rendering provenance."""

    model_config = ConfigDict(extra="forbid", strict=True)

    author_request: NonemptyText
    question_text: NonemptyText
    rendering_version: str = Field(
        default="plain-text-v1", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    representation_limitations: list[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
        ]
    ] = Field(default_factory=list, max_length=20)

    @field_validator("author_request", "question_text", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").strip()
        return value

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()


class RelevanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    tool: Literal["assess_relevance"] = "assess_relevance"
    version: Literal["1.0.0"] = "1.0.0"
    advisory: Literal[True] = True
    status: Literal["assessed", "error"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_sha256: str
    rendering_version: str
    representation_limitations: list[str]
    similarity: SimilarityReport
    duration_ms: float = Field(ge=0)
