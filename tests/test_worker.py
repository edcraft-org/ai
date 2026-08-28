from edcraft_validator._worker import execute_request


def test_executes_request_and_returns_trace_summary() -> None:
    # The worker should execute safe code and expose the authoritative answer
    # together with the trace evidence used by the validator.
    response = execute_request(
        {
            "code": "def total(values):\n    return sum(values)",
            "entry_function": "total",
            "inputs": {"values": [2, 3]},
        }
    )

    assert response["ok"] is True
    assert response["answer"] == 5
    assert response["trace_summary"]["entry_function"] == "total"
    assert response["trace_summary"]["function_calls"] >= 1


def test_reports_runtime_failures_without_raising() -> None:
    # User-generated code failures must become structured results for callers.
    response = execute_request(
        {
            "code": "def fail():\n    return 1 / 0",
            "entry_function": "fail",
            "inputs": {},
        }
    )

    assert response == {
        "ok": False,
        "error_code": "EXECUTION_FAILED",
        "error_message": "ZeroDivisionError: division by zero",
    }


def test_reports_non_json_return_values() -> None:
    # Results crossing the worker boundary must remain JSON-compatible.
    response = execute_request(
        {
            "code": "def make_set():\n    return {1, 2}",
            "entry_function": "make_set",
            "inputs": {},
        }
    )

    assert response["ok"] is False
    assert response["error_code"] == "UNSUPPORTED_RESULT"


def test_reports_execution_timeout() -> None:
    # The worker-local timer must stop non-terminating generated programs.
    response = execute_request(
        {
            "code": "def wait():\n    while True:\n        pass",
            "entry_function": "wait",
            "inputs": {},
            "timeout_seconds": 0.01,
        }
    )

    assert response["ok"] is False
    assert response["error_code"] == "EXECUTION_TIMEOUT"
    assert "0.01 seconds" in response["error_message"]


def test_rejects_non_finite_return_values() -> None:
    # NaN and infinity are rejected because they are not valid JSON answers.
    response = execute_request(
        {
            "code": "def answer():\n    return float('nan')",
            "entry_function": "answer",
            "inputs": {},
        }
    )

    assert response["ok"] is False
    assert response["error_code"] == "UNSUPPORTED_RESULT"
