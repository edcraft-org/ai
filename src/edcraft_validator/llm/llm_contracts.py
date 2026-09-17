"""Shared request, provider, and selection contracts for LLM calls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass(frozen=True)
class StructuredGenerationRequest[ProposalT: BaseModel]:
    """Domain-owned prompt, response schema, and response parser."""

    messages: list[dict[str, str]]
    response_model: type[BaseModel]
    parse_response: Callable[[str], ProposalT]
    prompt_version: str
    schema_name: str = "template_proposal"


class ModelProvider(Protocol):
    """Domain-agnostic structured-generation provider."""

    provider: str
    model: str

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT: ...


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
