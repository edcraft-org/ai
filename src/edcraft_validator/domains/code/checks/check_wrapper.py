"""Named code checks with consistent metadata and failure diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.domains.code.code_schemas import TemplateValidationError
from edcraft_validator.validation.validation_contracts import (
    AssuranceLevel,
    CheckResult,
)

# These outcomes mean verification could not finish, not that an answer is wrong.
_INCOMPLETE_TOOL_CODES = {
    "EXECUTION_TIMEOUT",
    "RESOURCE_LIMIT_EXCEEDED",
    "TRACE_LIMIT_EXCEEDED",
    "TOOL_FAILURE",
    "INVALID_TOOL_OUTPUT",
}


@dataclass(frozen=True)
class CodeCheck:
    name: str
    assurance: AssuranceLevel
    operation: Callable[[CodeValidationContext], CheckResult | None]
    details: Callable[[CodeValidationContext], dict[str, Any]]

    def run(self, context: CodeValidationContext) -> CheckResult | None:
        details = self.details(context)
        try:
            result = self.operation(context)
        except TemplateValidationError as exc:
            details.update(exc.context)
            return CheckResult(
                status="incomplete" if exc.code in _INCOMPLETE_TOOL_CODES else "failed",
                details=details,
                failure=exc,
            )
        if result is not None:
            result.details = {**details, **result.details}
        return result
