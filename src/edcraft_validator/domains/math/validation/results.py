"""Tri-state results shared by every math answer-type primitive."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PrimitiveStatus = Literal["passed", "failed", "inconclusive"]


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PrimitiveResult(Result):
    primitive: str
    status: PrimitiveStatus
    reason: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class OptionCheck(Result):
    index: int = Field(ge=0)
    value: str
    misconception: str = ""
    result: PrimitiveResult


class ValidationReport(Result):
    status: PrimitiveStatus
    answer: str = ""
    primitives: list[PrimitiveResult] = Field(default_factory=list)
    options: list[OptionCheck] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "passed"
