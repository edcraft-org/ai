import json
import sys
from typing import Any

from step_tracer import BranchExecution, FunctionCall, LoopExecution, StepTracer


def _respond(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, allow_nan=False))


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
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
            _respond(
                {
                    "ok": False,
                    "error_code": "ENTRY_RESULT_NOT_FOUND",
                    "error_message": (
                        "Could not identify exactly one entry-function call"
                    ),
                }
            )
            return

        answer = entry_calls[0].return_value
        try:
            json.dumps(answer, allow_nan=False)
        except (TypeError, ValueError):
            _respond(
                {
                    "ok": False,
                    "error_code": "UNSUPPORTED_RESULT",
                    "error_message": "The return value is not JSON-compatible",
                }
            )
            return

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
        _respond({"ok": True, "answer": answer, "trace_summary": summary})
    except Exception as exc:
        try:
            _respond(
                {
                    "ok": False,
                    "error_code": "EXECUTION_FAILED",
                    "error_message": f"{type(exc).__name__}: {exc}",
                }
            )
        except (TypeError, ValueError):
            _respond(
                {
                    "ok": False,
                    "error_code": "UNSUPPORTED_RESULT",
                    "error_message": "The return value is not JSON-compatible",
                }
            )


if __name__ == "__main__":
    main()
