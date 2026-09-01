from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from edcraft_validator.generation.models import TemplateAuthoringRequest

if TYPE_CHECKING:
    from edcraft_validator.domains.code.templates import CodeQuestionTemplate


class GenerationError(RuntimeError):
    """Raised when a provider cannot produce a usable template."""


class QuestionTemplateGenerator(Protocol):
    """Provider contract for authoring one reusable question template."""

    def generate_template(
        self, request: TemplateAuthoringRequest
    ) -> CodeQuestionTemplate: ...
