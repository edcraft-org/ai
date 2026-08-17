import json
import signal
import sys
from typing import Any

from step_tracer import BranchExecution, FunctionCall, LoopExecution, StepTracer


class ExecutionTimedOutError(TimeoutError):
    pass


def _raise_execution_timeout(signum: int, frame: Any) -> None:
    raise ExecutionTimedOutError


def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one trusted request; production callers must use the container."""
    timeout_seconds = request.get("timeout_seconds")
    timer_enabled = timeout_seconds is not None and hasattr(signal, "setitimer")
    try:
        if timer_enabled:
            signal.signal(signal.SIGALRM, _raise_execution_timeout)
            signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))

        entry_function = request["entry_function"]
        invocation = f"\n\n{entry_function}(**{request['inputs']!r})"

        tracer = StepTracer()
        transformed = tracer.transform_code(request["code"] + invocation)
        context = tracer.execute_transformed_code(transformed)

        entry_calls = [
            event
            for event in context.execution_trace
            if isinstance(event, FunctionCall)
            and event.name == entry_function
            and event.func_call_exec_ctx_id == 0
        ]
        if len(entry_calls) != 1:
            return {
                "ok": False,
                "error_code": "ENTRY_RESULT_NOT_FOUND",
                "error_message": "Could not identify exactly one entry-function call",
            }

        answer = entry_calls[0].return_value
        try:
            json.dumps(answer, allow_nan=False)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error_code": "UNSUPPORTED_RESULT",
                "error_message": "The return value is not JSON-compatible",
            }

        summary = {
            "entry_function": entry_function,
            "function_calls": sum(
                isinstance(event, FunctionCall) for event in context.execution_trace
            ),
            "loop_executions": sum(
                isinstance(event, LoopExecution) for event in context.execution_trace
            ),
            "branch_executions": sum(
                isinstance(event, BranchExecution) for event in context.execution_trace
            ),
            "variable_snapshots": len(context.variables),
        }
        return {"ok": True, "answer": answer, "trace_summary": summary}
    except ExecutionTimedOutError:
        return {
            "ok": False,
            "error_code": "EXECUTION_TIMEOUT",
            "error_message": f"Execution exceeded {timeout_seconds:g} seconds",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "EXECUTION_FAILED",
            "error_message": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if timer_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        response = execute_request(request)
    except Exception as exc:
        response = {
            "ok": False,
            "error_code": "INVALID_REQUEST",
            "error_message": f"{type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(response, allow_nan=False))


if __name__ == "__main__":
    main()
