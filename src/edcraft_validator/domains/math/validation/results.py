"""Tri-state results shared by the engine and form checks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CheckStatus = Literal["passed", "failed", "inconclusive"]


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CheckResult(Result):
    check: str
    status: CheckStatus
    reason: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class OptionCheck(Result):
    index: int = Field(ge=0)
    value: str
    misconception: str = ""
    result: CheckResult


class ValidationReport(Result):
    status: CheckStatus
    answer: str = ""
    checks: list[CheckResult] = Field(default_factory=list)
    options: list[OptionCheck] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "passed"
