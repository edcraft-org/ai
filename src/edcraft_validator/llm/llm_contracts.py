"""Shared request, provider, and selection contracts for LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecommendedCheckArguments(BaseModel):
    """Reserved closed argument object until checks are exposed as typed tools."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RecommendedCheck(BaseModel):
    """One model-recommended validation check in the fixed plan."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    arguments: RecommendedCheckArguments


class PlannedGenerationResponse[ProposalT: BaseModel](BaseModel):
    """A reusable proposal and the fixed checks recommended in the same response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    proposal: ProposalT
    checks: list[RecommendedCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_check_names(self) -> PlannedGenerationResponse[ProposalT]:
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("recommended check names must be unique")
        return self


@dataclass(frozen=True)
class StructuredGenerationRequest[ProposalT: BaseModel]:
    """Domain-owned prompt and response schema."""

    messages: list[dict[str, str]]
    response_model: type[ProposalT]
    prompt_version: str
    schema_name: str = "template_proposal"
    offered_tool_names: tuple[str, ...] = ()


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
