"""Ports for validation tools and domain validation pipelines."""

from typing import Protocol

from edcraft_validator.validation.contracts import (
    ToolResult,
    ValidationContext,
    ValidationRun,
)


class ValidationTool(Protocol):
    """A focused check with one responsibility."""

    name: str

    def validate(self, context: ValidationContext) -> ToolResult: ...


class ValidationPipeline(Protocol):
    """A domain-specific composition of validation tools."""

    def compute_answer(self, context: ValidationContext) -> ValidationRun: ...

    def validate(self, context: ValidationContext) -> ValidationRun: ...
