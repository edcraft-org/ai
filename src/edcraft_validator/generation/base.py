from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from edcraft_validator.generation.models import TemplatePromptMetadata


class GenerationError(RuntimeError):
    """Raised when a provider cannot produce a usable structured result."""

    category = "generation_error"


class GenerationTimeoutError(GenerationError):
    category = "timeout"


class GenerationTransportError(GenerationError):
    category = "transport"


class GenerationResponseError(GenerationError):
    category = "invalid_response"


class GenerationSchemaError(GenerationError):
    category = "schema_validation"


@dataclass(frozen=True)
class StructuredGenerationRequest[ProposalT: BaseModel]:
    """Domain-owned prompt, response schema, and response parser."""

    messages: list[dict[str, str]]
    response_model: type[BaseModel]
    parse_response: Callable[[str], ProposalT]
    prompt_version: str
    schema_name: str = "template_proposal"

    def prompt_metadata(self) -> TemplatePromptMetadata:
        return build_prompt_metadata(self.prompt_version, self.messages)


class ModelProvider(Protocol):
    """Domain-agnostic structured-generation provider."""

    provider: str
    model: str

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT: ...


def build_prompt_metadata(
    version: str, messages: list[dict[str, str]]
) -> TemplatePromptMetadata:
    payload = json.dumps(messages, sort_keys=True, separators=(",", ":")).encode()
    return TemplatePromptMetadata(
        version=version,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
