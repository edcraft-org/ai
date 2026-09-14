"""Small check adapter around existing code-domain validation operations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edcraft_validator.validation.contracts import AssuranceLevel, CheckResult

from .context import CodeValidationContext
from .models import TemplateValidationError

# These outcomes mean verification could not finish, not that an answer is wrong.
_INCOMPLETE_TOOL_CODES = {
    "EXECUTION_TIMEOUT",
    "RESOURCE_LIMIT_EXCEEDED",
    "TOOL_FAILURE",
    "INVALID_TOOL_OUTPUT",
}


@dataclass(frozen=True)
class CodeCheck:
    name: str
    assurance: AssuranceLevel
    operation: Callable[[CodeValidationContext, dict[str, Any]], None]
    details: Callable[[CodeValidationContext], dict[str, Any]]
    applies: Callable[[CodeValidationContext], bool] = lambda context: True

    def run(self, context: CodeValidationContext) -> CheckResult | None:
        if not self.applies(context):
            return None
        details = self.details(context)
        try:
            self.operation(context, details)
        except TemplateValidationError as exc:
            details.update(exc.context)
            return CheckResult(
                status="incomplete" if exc.code in _INCOMPLETE_TOOL_CODES else "failed",
                details=details,
                failure=exc,
            )
        return CheckResult(details=details)
