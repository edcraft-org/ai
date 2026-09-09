"""Contract implemented by every EdCraft question domain."""

from typing import Protocol

from pydantic import BaseModel

from edcraft_validator.generation.base import StructuredGenerationRequest
from edcraft_validator.generation.models import ValidatedTemplateArtifact


class DomainModule(Protocol):
    """Domain-specific behavior used by the generic application workflow."""

    name: str
    request_model: type[BaseModel]
    candidate_model: type[BaseModel]
    validated_model: type[ValidatedTemplateArtifact]

    def generation_request(
        self, request: BaseModel, *, provider: str
    ) -> StructuredGenerationRequest: ...

    def build_candidate(self, request: BaseModel, proposal: BaseModel) -> BaseModel: ...

    def validate(
        self, candidate: BaseModel, *, request: BaseModel | None = None
    ) -> ValidatedTemplateArtifact: ...

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, seed: int
    ) -> BaseModel: ...
