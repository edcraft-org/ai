"""Shared checked-summary shape and evidence reader for property checking.

Every domain checks templates with the same limited property checker, so every
domain's checked summary carries the same coverage fields and applies the same
rules. Domain summaries extend :class:`PropertyCheckSummary` instead of
repeating the fields and their validator.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.validation.validation_contracts import ValidationEvidence

_PROPERTY_FIELDS = (
    "checking_mode",
    "examples_checked",
    "execution_calls",
    "max_examples",
    "max_execution_calls",
    "timeout_seconds",
    "seed",
    "whole_domain",
)


class PropertyCheckSummary(BaseModel):
    """The checking coverage and evidence every checked template shares."""

    model_config = ConfigDict(extra="forbid", strict=True)

    checking_mode: Literal["property_based"]
    examples_checked: int = Field(ge=1)
    execution_calls: int = Field(ge=1)
    max_examples: int = Field(ge=1)
    max_execution_calls: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    seed: int
    whole_domain: bool
    evidence: list[ValidationEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def require_successful_unique_evidence(self) -> PropertyCheckSummary:
        checks = [item.check for item in self.evidence]
        if len(checks) != len(set(checks)):
            raise ValueError("validation evidence checks must be unique")

        if any(
            item.status != "passed" and item.details.get("advisory") is not True
            for item in self.evidence
        ):
            raise ValueError("checked templates require passing validation evidence")

        if (
            not self.examples_checked
            <= self.execution_calls
            <= self.max_execution_calls
        ):
            raise ValueError("sample and execution counts exceed the checking budget")
        return self


def property_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Return just the property-check fields from a tool's evidence details."""
    missing = [name for name in _PROPERTY_FIELDS if name not in details]
    if missing:
        raise ValueError("property check details are missing: " + ", ".join(missing))
    return {name: details[name] for name in _PROPERTY_FIELDS}
