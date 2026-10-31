"""Evidence retained for successful, failed and incomplete authoring jobs."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SerializeAsAny

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.llm.llm_contracts import RecommendedCheck
from edcraft_validator.llm.usage import ModelCallRecord, ModelUsageSummary
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding

FailureStage = Literal[
    "configuration",
    "generation",
    "template_building",
    "checking",
    "validation",
    "finalization",
    "unexpected",
]


class AuthoringError(BaseModel):
    """The terminal workflow error, separate from earlier check findings."""

    stage: FailureStage
    code: str


class CheckExecution(BaseModel):
    # Application-generated execution ID; historical records retain provider IDs.
    call_id: str
    tool: str
    # The enclosing attempt stores the candidate supplied to this call.
    requested_arguments: dict[str, Any] | str
    application_arguments: dict[str, Any] | None = None
    evidence: ToolEvidence | None = None
    error: str | None = None
    skip_reason: str | None = None

    def model_feedback(self) -> dict[str, Any]:
        """Send verdicts and repair context; retain full records in the application."""
        evidence = None
        if self.evidence is not None:
            evidence = self.evidence.model_dump(
                mode="json", include={"status", "findings", "details"}
            )
            if self.evidence.status == "passed" and not self.evidence.findings:
                evidence.pop("details")
        feedback = {"tool": self.tool, "error": self.error, "evidence": evidence}
        if self.skip_reason:
            feedback["skip_reason"] = self.skip_reason
        return feedback

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.evidence is not None
            and (self.evidence.status == "passed")
        )


class GenerationAttempt(BaseModel):
    number: int
    candidate: dict[str, Any]
    executions: list[CheckExecution] = Field(default_factory=list)
    pending: list[str]
    complete: bool = False
    passed: bool = False


class AuthoringResult(BaseModel):
    status: Literal["checked", "needs_review", "error"]
    provider: str
    model: str
    domain: str
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request: dict[str, Any]
    prompt_version: str
    # Absent in historical records and existing-candidate validation jobs.
    revision_policy: str | None = None
    duration_ms: float = 0
    generation_duration_ms: float = 0
    model_calls: list[ModelCallRecord] = Field(default_factory=list)
    usage: ModelUsageSummary = Field(default_factory=ModelUsageSummary)
    feedback_error: str | None = None
    failure: AuthoringError | None = None
    fixed_plan: list[str]
    check_plan: list[RecommendedCheck] = Field(default_factory=list)
    tool_catalogue: list[dict[str, Any]]
    attempts: list[GenerationAttempt] = Field(default_factory=list)
    artifact: SerializeAsAny[ValidatedTemplateArtifact] | None = None
    reason: str | None = None
    warnings: list[ToolFinding] = Field(default_factory=list)


class AuthoringFailure(ValueError):
    """Compatibility wrapper failure, retaining the complete reviewable result."""

    def __init__(self, result: AuthoringResult):
        super().__init__(result.reason or result.status)
        self.result = result
