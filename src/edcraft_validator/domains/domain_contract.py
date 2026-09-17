"""Contract implemented by every EdCraft question domain."""

from typing import Protocol

from pydantic import BaseModel

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.validation.validation_contracts import (
    ValidationPlan,
    ValidationReport,
)


class DomainModule[ContextT](Protocol):
    """Domain-specific behavior used by the generic application workflow."""

    name: str
    request_model: type[BaseModel]
    candidate_model: type[BaseModel]
    validated_model: type[ValidatedTemplateArtifact]

    def generation_request(self, request: BaseModel) -> StructuredGenerationRequest: ...

    def build_candidate(self, request: BaseModel, proposal: BaseModel) -> BaseModel: ...

    def prepare_validation(
        self, candidate: BaseModel, *, request: BaseModel | None = None
    ) -> ValidationPlan[ContextT]: ...

    def finalize_template(
        self, context: ContextT, report: ValidationReport
    ) -> ValidatedTemplateArtifact: ...

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, seed: int
    ) -> BaseModel: ...
