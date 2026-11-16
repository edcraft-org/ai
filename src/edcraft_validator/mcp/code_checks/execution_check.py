"""Execution-backed validation for code templates."""

from dataclasses import dataclass
from typing import Any

from edcraft_validator.domains.code.code_schemas import TemplateValidationError
from edcraft_validator.mcp.code_checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.tools.python_execution import (
    ExecutionResult,
    PythonExecutionTool,
)

_LIMIT_FAILURES = {
    "EXECUTION_TIMEOUT": "took longer than the time limit",
    "RESOURCE_LIMIT_EXCEEDED": "used too much memory",
    "TRACE_LIMIT_EXCEEDED": "ran too long",
}
_LIMIT_GUIDANCE = (
    "Reduce the largest parameter values or simplify the loops so every input "
    "stays well within the limit."
)


def _failure_message(inputs: dict[str, Any], execution: ExecutionResult) -> str:
    detail = execution.error_message or execution.error_code or "unknown"
    summary = _LIMIT_FAILURES.get(execution.error_code or "")
    if summary is None:
        return f"template execution failed for inputs {inputs}: {detail}"

    formatted = ", ".join(f"{name}={value}" for name, value in inputs.items())
    return f"The program {summary} for inputs {formatted}: {detail}. {_LIMIT_GUIDANCE}"


@dataclass(frozen=True)
class ExecutionCheck:
    """Run sampled cases using an injected, timeout-bound execution tool."""

    execution_tool: PythonExecutionTool
    timeout_seconds: float = 2.0

    def run(self, context: CodeValidationContext) -> None:
        executions = self.execution_tool.execute_batch(
            context.template.code,
            context.template.entry_function,
            context.inputs_cases,
            timeout_seconds=self.timeout_seconds,
        )

        if len(executions) != len(context.inputs_cases):
            raise TemplateValidationError(
                "executor returned the wrong number of batch results",
                code="EXECUTOR_PROTOCOL_ERROR",
                field="code",
            )

        for inputs, execution in zip(context.inputs_cases, executions, strict=True):
            if execution.ok:
                continue
            raise TemplateValidationError(
                _failure_message(inputs, execution),
                code=execution.error_code or "EXECUTION_FAILED",
                field="code",
                inputs=inputs,
            )

        context.executions = executions
