from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from edcraft_validator.generation.models import TemplateAuthoringRequest

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

    def generate_proposal(
        self, request: TemplateAuthoringRequest
    ) -> CodeTemplateProposal: ...
