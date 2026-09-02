import json
import signal
import sys
from typing import Any

from step_tracer import BranchExecution, FunctionCall, LoopExecution, StepTracer

DEFAULT_TRACE_EVENT_LIMIT = 100_000


class ExecutionTimedOutError(TimeoutError):
    pass


class TraceLimitExceededError(RuntimeError):
    pass


def _raise_execution_timeout(signum: int, frame: Any) -> None:
    raise ExecutionTimedOutError


def _execute_with_trace_limit(
    tracer: StepTracer, transformed_code: str, trace_event_limit: int
) -> Any:
    """Execute transformed user code with a bounded number of Python line events."""
    events = 0

    def count_user_code_events(frame: Any, event: str, _arg: Any) -> Any:
        nonlocal events
        if frame.f_code.co_filename != "<string>":
            return None
        if event == "line":
            events += 1
            if events > trace_event_limit:
                raise TraceLimitExceededError
        return count_user_code_events

    previous_trace = sys.gettrace()
    sys.settrace(count_user_code_events)
    try:
        return tracer.execute_transformed_code(transformed_code)
    finally:
        sys.settrace(previous_trace)


def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one trusted request; production callers must use the container."""
    timeout_seconds = request.get("timeout_seconds")
    trace_event_limit = request.get("trace_event_limit", DEFAULT_TRACE_EVENT_LIMIT)
    if (
        not isinstance(trace_event_limit, int)
        or isinstance(trace_event_limit, bool)
        or trace_event_limit <= 0
    ):
        return {
            "ok": False,
            "error_code": "INVALID_REQUEST",
            "error_message": "trace_event_limit must be a positive integer",
        }
    timer_enabled = timeout_seconds is not None and hasattr(signal, "setitimer")
    try:
        if timer_enabled:
            signal.signal(signal.SIGALRM, _raise_execution_timeout)
            signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))

        entry_function = request["entry_function"]
        invocation = f"\n\n{entry_function}(**{request['inputs']!r})"

        tracer = StepTracer()
        transformed = tracer.transform_code(request["code"] + invocation)
        context = _execute_with_trace_limit(tracer, transformed, trace_event_limit)

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
            "loop_iterations": sum(
                event.num_iterations
                for event in context.execution_trace
                if isinstance(event, LoopExecution)
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
    except TraceLimitExceededError:
        return {
            "ok": False,
            "error_code": "TRACE_LIMIT_EXCEEDED",
            "error_message": (
                f"Execution exceeded the {trace_event_limit} trace-event limit"
            ),
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


def execute_batch_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute several input combinations for the same program in one worker."""
    cases = request["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    common = {
        "code": request["code"],
        "entry_function": request["entry_function"],
        "timeout_seconds": request.get("timeout_seconds"),
    }
    return {
        "ok": True,
        "results": [
            execute_request({**common, "inputs": case["inputs"]}) for case in cases
        ],
    }


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        response = (
            execute_batch_request(request)
            if "cases" in request
            else execute_request(request)
        )
    except Exception as exc:
        response = {
            "ok": False,
            "error_code": "INVALID_REQUEST",
            "error_message": f"{type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(response, allow_nan=False))


if __name__ == "__main__":
    main()
