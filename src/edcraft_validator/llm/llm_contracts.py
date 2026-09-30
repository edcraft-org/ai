"""Shared request, provider, and selection contracts for LLM calls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecommendedCheckArguments(BaseModel):
    """Reserved closed argument object until checks are exposed as typed tools."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RecommendedCheck(BaseModel):
    """One model-recommended validation check in the fixed plan."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    arguments: RecommendedCheckArguments


class CheckPlanResponse(BaseModel):
    """Model-selected checks for a supplied candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    checks: list[RecommendedCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_check_names(self) -> CheckPlanResponse:
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("recommended check names must be unique")
        return self


class PlannedGenerationResponse[ProposalT: BaseModel](CheckPlanResponse):
    """A reusable proposal and the fixed checks recommended in the same response."""

    proposal: ProposalT


@dataclass(frozen=True, slots=True)
class ToolCatalogueSnapshot:
    """Immutable MCP definitions offered for one authoring job."""

    definitions_json: str
    names: tuple[str, ...]

    @classmethod
    def from_definitions(
        cls, definitions: tuple[dict[str, Any], ...]
    ) -> ToolCatalogueSnapshot:
        return cls(
            definitions_json=json.dumps(
                definitions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            names=tuple(definition["name"] for definition in definitions),
        )

    def definitions(self) -> list[dict[str, Any]]:
        """Return a writable copy for JSON provenance and external consumers."""
        return json.loads(self.definitions_json)


@dataclass(frozen=True)
class StructuredGenerationRequest[ProposalT: BaseModel]:
    """Domain-owned prompt and response schema."""

    messages: list[dict[str, Any]]
    response_model: type[ProposalT]
    prompt_version: str
    schema_name: str = "template_proposal"
    offered_tool_names: tuple[str, ...] = ()
    tool_catalogue: ToolCatalogueSnapshot | None = None


class ModelProvider(Protocol):
    """Domain-agnostic structured-generation provider."""

    provider: str
    model: str

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT: ...

    def tool_turn(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelTurn: ...


class ToolCall(BaseModel):
    """Provider-normalized call; malformed argument JSON is retained for feedback."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments_json: str


class ModelTurn(BaseModel):
    content: str = ""
    calls: list[ToolCall] = Field(default_factory=list)

    def message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments_json,
                    },
                }
                for call in self.calls
            ]
        return message


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
