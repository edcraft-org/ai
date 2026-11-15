"""Local adapter for executing a batch with the Python tracing tool."""

from dataclasses import dataclass, replace
from typing import Any, Protocol

from edcraft_validator.tools.isolated_process import (
    DEFAULT_MEMORY_LIMIT_BYTES,
    CodedWorkerError,
    MemoryLimitUnavailable,
    cpu_limit_for_timeout,
    run_json_worker,
)

WORKER_MODULE = "edcraft_validator.tools.python_worker"


class PythonToolTimeout(TimeoutError):
    """The Python execution worker exceeded its wall-clock deadline."""


class PythonToolWorkerError(CodedWorkerError):
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
        except RuntimeError as exc:
            return _worker_failure(exc)

        return response


def _worker_failure(exc: RuntimeError) -> ExecutionResult:
    """Map a runner failure onto the historical execution error codes.

    The error message can contain up to ``MAX_STDERR_CHARS`` of the untrusted
    program's stderr, so classification uses only the exception type and the
    runner's ``failure_kind`` marker.
    """
    if isinstance(exc, PythonToolMemoryError):
        return ExecutionResult(
            ok=False,
            error_code="RESOURCE_LIMIT_EXCEEDED",
            error_message="Python tool was stopped by an operating-system limit",
        )
    if isinstance(exc, MemoryLimitUnavailable):
        # The runner builds this as a subclass of the caller's worker error. It
        # is a policy gap rather than a limit violation, so it stays a failure.
        return _tool_failure(exc)
    if isinstance(exc, CodedWorkerError):
        if exc.failure_kind == "signal":
            return ExecutionResult(
                ok=False,
                error_code="RESOURCE_LIMIT_EXCEEDED",
                error_message="Python tool was stopped by an operating-system limit",
            )
        if exc.failure_kind == "invalid_output":
            return ExecutionResult(
                ok=False,
                error_code="INVALID_TOOL_OUTPUT",
                error_message="Python tool returned invalid JSON",
            )
    return _tool_failure(exc)


def _tool_failure(exc: RuntimeError) -> ExecutionResult:
    return ExecutionResult(
        ok=False,
        error_code="TOOL_FAILURE",
        error_message=str(exc) or "Python tool failed",
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
