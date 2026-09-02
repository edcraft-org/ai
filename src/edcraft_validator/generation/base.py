from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Protocol

from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplatePromptMetadata,
)

if TYPE_CHECKING:
    from edcraft_validator.domains.code.templates import CodeTemplateProposal


class GenerationError(RuntimeError):
    """Raised when a provider cannot produce a usable template."""

    category = "generation_error"


class GenerationTimeoutError(GenerationError):
    category = "timeout"


class GenerationTransportError(GenerationError):
    category = "transport"


class GenerationResponseError(GenerationError):
    category = "invalid_response"


class GenerationSchemaError(GenerationError):
    category = "schema_validation"


class QuestionTemplateGenerator(Protocol):
    """Provider contract for authoring one reusable question template."""

    provider: str
    model: str

    def generate_proposal(
        self, request: TemplateAuthoringRequest
    ) -> CodeTemplateProposal: ...

    def prompt_metadata(
        self, request: TemplateAuthoringRequest
    ) -> TemplatePromptMetadata: ...


def build_prompt_metadata(
    version: str, messages: list[dict[str, str]]
) -> TemplatePromptMetadata:
    payload = json.dumps(messages, sort_keys=True, separators=(",", ":")).encode()
    return TemplatePromptMetadata(
        version=version,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
