"""Contract implemented by every EdCraft question domain."""

from typing import Any, Protocol

from pydantic import BaseModel

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.mcp.evidence import ToolEvidence


class DomainModule(Protocol):
    """Domain-specific behavior used by the generic application workflow."""

    name: str
    request_model: type[BaseModel]
    candidate_model: type[BaseModel]
    validated_model: type[ValidatedTemplateArtifact]
    allowed_tool_names: tuple[str, ...]

    def generation_request(self, request: BaseModel) -> StructuredGenerationRequest: ...

    def validation_request(
        self, candidate: BaseModel
    ) -> StructuredGenerationRequest: ...

    def build_candidate(self, request: BaseModel, proposal: BaseModel) -> BaseModel: ...

    def tool_bindings(
        self, request: BaseModel | None, candidate: BaseModel, tool_name: str
    ) -> dict[str, Any]: ...

    def finalize_checked_template(
        self, candidate: BaseModel, evidence: list[ToolEvidence]
    ) -> ValidatedTemplateArtifact: ...

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, seed: int
    ) -> BaseModel: ...
