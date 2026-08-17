import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class ExecutionResult:
    ok: bool
    answer: Any | None = None
    trace_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


def execute_with_tracer(
    code: str,
    entry_function: str,
    inputs: dict[str, Any],
    *,
    timeout_seconds: float = 2.0,
) -> ExecutionResult:
    payload = json.dumps(
        {"code": code, "entry_function": entry_function, "inputs": inputs},
        allow_nan=False,
    )
    try:
        process = subprocess.run(
            [sys.executable, "-m", "edcraft_validator._worker"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            ok=False,
            error_code="EXECUTION_TIMEOUT",
            error_message=f"Execution exceeded {timeout_seconds:g} seconds",
        )

    if process.returncode != 0:
        message = process.stderr.strip() or "Worker exited unexpectedly"
        return ExecutionResult(
            ok=False,
            error_code="WORKER_FAILURE",
            error_message=message[-1000:],
        )

    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        return ExecutionResult(
            ok=False,
            error_code="INVALID_WORKER_OUTPUT",
            error_message="Execution worker returned invalid JSON",
        )

    return ExecutionResult(
        ok=result["ok"],
        answer=result.get("answer"),
        trace_summary=result.get("trace_summary"),
        error_code=result.get("error_code"),
        error_message=result.get("error_message"),
    )

