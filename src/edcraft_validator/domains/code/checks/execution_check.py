"""Execution-backed validation for code templates."""

from dataclasses import dataclass

from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.domains.code.code_schemas import TemplateValidationError
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.validation_contracts import CheckResult


@dataclass(frozen=True)
class ExecutionCheck:
    """Run all finite cases using an injected, timeout-bound execution tool."""

    execution_tool: PythonExecutionTool
    timeout_seconds: float = 2.0

    def run(self, context: CodeValidationContext) -> CheckResult:
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
            detail = execution.error_message or execution.error_code or "unknown"
            raise TemplateValidationError(
                f"template execution failed for inputs {inputs}: {detail}",
                code=execution.error_code or "EXECUTION_FAILED",
                field="code",
                inputs=inputs,
            )
        context.executions = executions
        return CheckResult()
