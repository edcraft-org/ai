"""Local adapter for executing a batch with the Python tracing tool."""

import re
from dataclasses import dataclass, replace
from typing import Any, Protocol

from edcraft_validator.tools.isolated_process import (
    DEFAULT_MEMORY_LIMIT_BYTES,
    cpu_limit_for_timeout,
    run_json_worker,
)

WORKER_MODULE = "edcraft_validator.tools.python_worker"


class PythonToolTimeout(TimeoutError):
    """The Python execution worker exceeded its wall-clock deadline."""


class PythonToolWorkerError(RuntimeError):
    """The Python execution worker failed before returning a usable result."""


class PythonToolMemoryError(RuntimeError):
    """The Python execution worker exceeded its memory limit."""


@dataclass
class ExecutionResult:
    ok: bool
    answer: Any | None = None
    trace_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class PythonExecutionTool(Protocol):
    """Interface required by code-domain execution checks."""

    def execute_batch(
        self,
        code: str,
        entry_function: str,
        inputs: list[dict[str, Any]],
        *,
        timeout_seconds: float,
    ) -> list[ExecutionResult]: ...


class LocalPythonTool:
    """Run the packaged tracing worker in a local Python subprocess."""

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
            response = run_json_worker(
                payload,
                module=WORKER_MODULE,
                timeout_seconds=host_timeout,
                timeout_error=PythonToolTimeout,
                worker_error=PythonToolWorkerError,
                memory_error=PythonToolMemoryError,
                description="Python tool",
                worker_description="Python tool worker",
                cpu_seconds=cpu_limit_for_timeout(host_timeout),
                memory_bytes=DEFAULT_MEMORY_LIMIT_BYTES,
            )
        except TimeoutError:
            return ExecutionResult(
                ok=False,
                error_code="EXECUTION_TIMEOUT",
                error_message="Python tool exceeded its execution timeout",
            )
        except MemoryError:
            return ExecutionResult(
                ok=False,
                error_code="RESOURCE_LIMIT_EXCEEDED",
                error_message="Python tool was stopped by an operating-system limit",
            )
        except RuntimeError as exc:
            return _worker_failure(exc)

        if not isinstance(response, dict):
            return ExecutionResult(
                ok=False,
                error_code="INVALID_TOOL_OUTPUT",
                error_message="Python tool returned a non-object result",
            )
        return response


_OS_SIGNAL_EXIT = re.compile(r"exited with -\d+")
_INVALID_OUTPUT_MARKERS = ("returned invalid JSON", "returned a non-object")


def _worker_failure(exc: RuntimeError) -> ExecutionResult:
    """Map a runner failure onto the historical execution error codes.

    ``run_json_worker`` distinguishes memory failures with a dedicated error
    type. Its remaining transport failures all share one worker-error type, so
    the message is the only signal that separates invalid output and an
    operating-system kill from an ordinary worker crash.
    """
    message = str(exc)
    if isinstance(exc, PythonToolMemoryError) or (
        "memory limit" in message and "exceeded" in message
    ):
        return ExecutionResult(
            ok=False,
            error_code="RESOURCE_LIMIT_EXCEEDED",
            error_message="Python tool was stopped by an operating-system limit",
        )
    if any(marker in message for marker in _INVALID_OUTPUT_MARKERS):
        return ExecutionResult(
            ok=False,
            error_code="INVALID_TOOL_OUTPUT",
            error_message=(
                "Python tool returned invalid JSON"
                if "invalid JSON" in message
                else "Python tool returned a non-object result"
            ),
        )
    if _OS_SIGNAL_EXIT.search(message):
        return ExecutionResult(
            ok=False,
            error_code="RESOURCE_LIMIT_EXCEEDED",
            error_message="Python tool was stopped by an operating-system limit",
        )
    return ExecutionResult(
        ok=False,
        error_code="TOOL_FAILURE",
        error_message=message or "Python tool failed",
    )


def _to_result(result: dict[str, Any]) -> ExecutionResult:
    ok = result.get("ok") is True
    return ExecutionResult(
        ok=ok,
        answer=result.get("answer"),
        trace_summary=result.get("trace_summary"),
        error_code=result.get("error_code") if not ok else None,
        error_message=result.get("error_message") if not ok else None,
    )
