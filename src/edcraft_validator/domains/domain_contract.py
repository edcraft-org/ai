"""Contract implemented by every EdCraft question domain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.domain_support import ReviewTemplateView
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.mcp.tool_dependencies import ToolDependencies
from edcraft_validator.validation.check_contracts import ToolEvidence

if TYPE_CHECKING:
    from fastmcp import FastMCP


class DomainModule(Protocol):
    """Domain-specific behavior used by the generic application workflow."""

    name: str
    request_model: type[BaseModel]
    candidate_model: type[BaseModel]
    validated_model: type[ValidatedTemplateArtifact]
    question_model: type[BaseModel]
    # Human-readable review label for a candidate language, when it has one.
    template_language: str | None
    # Shared checks this domain opts into, selected by ``capability:<name>``.
    capabilities: frozenset[str]

    def register_tools(self, server: FastMCP, dependencies: ToolDependencies) -> None:
        """Register the domain's MCP tools.

        A test checks that every registered domain registers at least one tool.
        """
        ...

    def review_view(
        self, artifact: ValidatedTemplateArtifact
    ) -> ReviewTemplateView | None: ...

    def generation_request(self, request: BaseModel) -> StructuredGenerationRequest: ...

    def build_candidate(self, request: BaseModel, proposal: BaseModel) -> BaseModel: ...

    def tool_bindings(
        self, request: BaseModel, candidate: BaseModel, tool_name: str
    ) -> dict[str, Any]: ...

    def distractor_count(self, candidate: BaseModel) -> int:
        """Number of distractors the candidate offers for the requested count."""
        ...

    def required_checks(self, candidate: BaseModel) -> frozenset[str]:
        """Checks this candidate cannot be saved without.

        The application adds any the model did not select, so they must need
        no model-supplied arguments. Other offered checks stay optional.
        """
        ...

    def finalize_checked_template(
        self,
        candidate: BaseModel,
        evidence: list[ToolEvidence],
        *,
        advisory_checks: frozenset[str],
    ) -> ValidatedTemplateArtifact:
        """Package a checked candidate; ``advisory_checks`` never block it."""
        ...

    def checked_tool_bindings(
        self,
        request: BaseModel,
        candidate: BaseModel,
        tool_name: str,
        evidence: list[ToolEvidence],
    ) -> dict[str, Any]:
        """Bind tools tagged stage:after-validation to the checked reusable content."""
        ...

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, seed: int
    ) -> BaseModel: ...
