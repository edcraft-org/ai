"""Evidence retained for successful, failed and incomplete authoring jobs."""

from typing import Any, Literal

from pydantic import BaseModel, Field, SerializeAsAny

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.mcp.evidence import ToolEvidence


class CheckExecution(BaseModel):
    call_id: str
    tool: str
    candidate_digest: str
    requested_arguments: str
    effective_arguments: dict[str, Any] | None = None
    evidence: ToolEvidence | None = None
    error: str | None = None

    def model_feedback(self) -> dict[str, Any]:
        """Send verdicts and repair context; retain full records in the application."""
        evidence = None
        if self.evidence is not None:
            evidence = self.evidence.model_dump(
                mode="json", include={"status", "findings", "details"}
            )
            if self.evidence.status == "passed":
                evidence.pop("details")
        return {"tool": self.tool, "error": self.error, "evidence": evidence}

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.evidence is not None
            and (self.evidence.status == "passed")
        )


class GenerationAttempt(BaseModel):
    number: int
    proposal: dict[str, Any]
    candidate: dict[str, Any]
    candidate_digest: str
    executions: list[CheckExecution] = Field(default_factory=list)
    pending: list[str]
    complete: bool = False
    passed: bool = False


class AuthoringResult(BaseModel):
    status: Literal["checked", "needs_review", "error"]
    provider: str
    model: str
    request: dict[str, Any]
    prompt_version: str
    duration_ms: float = 0
    feedback_error: str | None = None
    proposal: dict[str, Any]
    fixed_plan: list[str]
    tool_catalogue: list[dict[str, Any]]
    attempts: list[GenerationAttempt] = Field(default_factory=list)
    artifact: SerializeAsAny[ValidatedTemplateArtifact] | None = None
    reason: str | None = None


class AuthoringFailure(ValueError):
    """Compatibility wrapper failure, retaining the complete reviewable result."""

    def __init__(self, result: AuthoringResult):
        super().__init__(result.reason or result.status)
        self.result = result
