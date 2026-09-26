"""Structured result contract shared by every MCP validation tool."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.validation.validation_contracts import AssuranceLevel

ToolStatus = Literal["passed", "failed", "error"]


class ToolFinding(BaseModel):
    """One actionable observation produced by a validation tool."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str = Field(min_length=1)
    severity: Literal["error", "warning"] = "error"
    field: str | None = None


class ToolEvidence(BaseModel):
    """Pass, validation failure, or execution error from one MCP tool call."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tool: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    status: ToolStatus
    assurance: AssuranceLevel
    findings: list[ToolFinding] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_findings_for_unsuccessful_results(self) -> "ToolEvidence":
        if self.status != "passed" and not self.findings:
            raise ValueError("failed and error results require at least one finding")
        return self
