"""Generic validation ports and evidence contracts."""

from edcraft_validator.validation.base import ValidationPipeline, ValidationTool
from edcraft_validator.validation.contracts import (
    ToolResult,
    ValidationContext,
    ValidationRun,
)

__all__ = [
    "ToolResult",
    "ValidationContext",
    "ValidationPipeline",
    "ValidationRun",
    "ValidationTool",
]
