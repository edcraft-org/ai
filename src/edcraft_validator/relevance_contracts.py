"""Domain-independent inputs and evidence for text relevance measurement."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from edcraft_validator.llm.decision import DecisionReport

NonemptyText = Annotated[str, StringConstraints(min_length=1, max_length=200_000)]


class RelevanceInput(BaseModel):
    """The author request and question text to compare."""

    model_config = ConfigDict(extra="forbid", strict=True)

    author_request: NonemptyText
    question_text: NonemptyText

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
    version: Literal["2.0.0"] = "2.0.0"
    advisory: Literal[True] = True
    status: Literal["assessed", "error"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_sha256: str
    decision: DecisionReport
    duration_ms: float = Field(ge=0)
