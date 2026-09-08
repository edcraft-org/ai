"""Local adapter for executing a batch with the Python tracing tool."""

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from typing import Any, Protocol


@dataclass
class ExecutionResult:
    ok: bool
    answer: Any | None = None
    trace_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class PythonExecutionTool(Protocol):
    """Interface required by code-domain execution checks."""

    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult: ...


class LocalPythonTool:
    """Run the packaged tracing worker in a local Python subprocess."""

    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        response = self._invoke(
            {
                "code": code,
                "entry_function": entry_function,
                "inputs": inputs,
                "timeout_seconds": timeout_seconds,
            },
            host_timeout=timeout_seconds + 1,
        )
        return (
            response if isinstance(response, ExecutionResult) else _to_result(response)
        )

    def execute_batch(
        self,
        code: str,
        entry_function: str,
        inputs: list[dict[str, Any]],
        *,
        timeout_seconds: float,
    ) -> list[ExecutionResult]:
        if not inputs:
            return []
        response = self._invoke(
            {
                "code": code,
                "entry_function": entry_function,
                "cases": [{"inputs": value} for value in inputs],
                "timeout_seconds": timeout_seconds,
            },
            host_timeout=timeout_seconds * len(inputs) + 1,
        )
        if isinstance(response, ExecutionResult):
            return [replace(response) for _ in inputs]
        results = response.get("results")
        if response.get("ok") is not True or not isinstance(results, list):
            failure = _to_result(response)
            return [replace(failure) for _ in inputs]
        if len(results) != len(inputs):
            failure = ExecutionResult(
                ok=False,
                error_code="INVALID_TOOL_OUTPUT",
                error_message="Python tool returned the wrong result count",
            )
            return [replace(failure) for _ in inputs]
        return [_to_result(result) for result in results]

    @staticmethod
    def _invoke(
        payload: dict[str, Any], *, host_timeout: float
    ) -> dict[str, Any] | ExecutionResult:
        try:
            process = subprocess.run(
                [sys.executable, "-m", "edcraft_validator.tools.python_worker"],
                input=json.dumps(payload, allow_nan=False),
                capture_output=True,
                text=True,
                timeout=host_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                ok=False,
                error_code="EXECUTION_TIMEOUT",
                error_message="Python tool exceeded its execution timeout",
            )

        if process.returncode != 0:
            return ExecutionResult(
                ok=False,
                error_code="TOOL_FAILURE",
                error_message=process.stderr.strip() or "Python tool failed",
            )
        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError:
            return ExecutionResult(
                ok=False,
                error_code="INVALID_TOOL_OUTPUT",
                error_message="Python tool returned invalid JSON",
            )
        if not isinstance(response, dict):
            return ExecutionResult(
                ok=False,
                error_code="INVALID_TOOL_OUTPUT",
                error_message="Python tool returned a non-object result",
            )
        return response


def _to_result(result: dict[str, Any]) -> ExecutionResult:
    ok = result.get("ok") is True
    return ExecutionResult(
        ok=ok,
        answer=result.get("answer"),
        trace_summary=result.get("trace_summary"),
        error_code=result.get("error_code") if not ok else None,
        error_message=result.get("error_message") if not ok else None,
    )
