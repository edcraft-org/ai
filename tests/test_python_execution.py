from typing import Any

from edcraft_validator.tools import python_execution
from edcraft_validator.tools.isolated_process import DEFAULT_MEMORY_LIMIT_BYTES
from edcraft_validator.tools.python_execution import LocalPythonTool


def successful_response(answer: object = 16) -> dict[str, Any]:
    return {
        "ok": True,
        "results": [
            {
                "ok": True,
                "answer": answer,
                "trace_summary": {"entry_function": "square"},
            }
        ],
    }


def test_runs_packaged_python_tool(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    def fake_run(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        observed["payload"] = payload
        observed["kwargs"] = kwargs
        return successful_response()

    monkeypatch.setattr(python_execution, "run_json_worker", fake_run)

    result = LocalPythonTool().execute_batch(
        "def square(x):\n    return x * x",
        "square",
        [{"x": 4}],
        timeout_seconds=2,
    )[0]

    assert result.ok
    assert result.answer == 16
    assert observed["kwargs"]["module"] == "edcraft_validator.tools.python_worker"
    assert observed["kwargs"]["timeout_seconds"] == 3
    assert observed["kwargs"]["memory_bytes"] >= DEFAULT_MEMORY_LIMIT_BYTES
    assert observed["kwargs"]["cpu_seconds"] >= observed["kwargs"]["timeout_seconds"]
    payload = observed["payload"]
    assert payload["cases"] == [{"inputs": {"x": 4}}]
    assert payload["timeout_seconds"] == 2


def test_runs_batch_in_one_worker(monkeypatch) -> None:
    calls = 0

    def fake_run(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        assert payload["cases"] == [
            {"inputs": {"x": 2}},
            {"inputs": {"x": 3}},
        ]
        return {
            "ok": True,
            "results": [
                {"ok": True, "answer": 4, "trace_summary": {}},
                {"ok": True, "answer": 9, "trace_summary": {}},
            ],
        }

    monkeypatch.setattr(python_execution, "run_json_worker", fake_run)

    results = LocalPythonTool().execute_batch(
        "def square(x):\n    return x * x",
        "square",
        [{"x": 2}, {"x": 3}],
        timeout_seconds=2,
    )

    assert calls == 1
    assert [result.answer for result in results] == [4, 9]


def test_empty_batch_does_not_start_a_worker(monkeypatch) -> None:
    def forbidden_worker(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("an empty batch must not start a worker")

    monkeypatch.setattr(python_execution, "run_json_worker", forbidden_worker)

    assert (
        LocalPythonTool().execute_batch(
            "def main():\n    return 1", "main", [], timeout_seconds=2
        )
        == []
    )


def test_timeout_is_reported(monkeypatch) -> None:
    def timed_out(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise python_execution.PythonToolTimeout("Python tool exceeded 1.1s")

    monkeypatch.setattr(python_execution, "run_json_worker", timed_out)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=0.1
    )[0]

    assert result.error_code == "EXECUTION_TIMEOUT"
    assert result.error_message == "Python tool exceeded its execution timeout"


def worker_error(message: str, failure_kind: str) -> Exception:
    error = python_execution.PythonToolWorkerError(message)
    error.failure_kind = failure_kind
    return error


def test_worker_crash_is_reported(monkeypatch) -> None:
    def crashed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise worker_error("worker failed", "exit")

    monkeypatch.setattr(python_execution, "run_json_worker", crashed)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "TOOL_FAILURE"
    assert result.error_message == "worker failed"


def test_memory_limit_is_reported(monkeypatch) -> None:
    def exhausted(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise python_execution.PythonToolMemoryError("memory limit exceeded")

    monkeypatch.setattr(python_execution, "run_json_worker", exhausted)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "RESOURCE_LIMIT_EXCEEDED"


def test_memory_limit_unavailable_is_reported_as_a_tool_failure(monkeypatch) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise python_execution.MemoryLimitUnavailable(
            "worker memory limit could not be enforced"
        )

    monkeypatch.setattr(python_execution, "run_json_worker", unavailable)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "TOOL_FAILURE"
    assert result.error_message == "worker memory limit could not be enforced"


def test_process_killed_by_resource_limit_is_reported(monkeypatch) -> None:
    def killed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise worker_error("Python tool worker exited with -9: ", "signal")

    monkeypatch.setattr(python_execution, "run_json_worker", killed)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "RESOURCE_LIMIT_EXCEEDED"


def test_invalid_worker_json_is_reported(monkeypatch) -> None:
    def invalid(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise worker_error("Python tool worker returned invalid JSON", "invalid_output")

    monkeypatch.setattr(python_execution, "run_json_worker", invalid)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "INVALID_TOOL_OUTPUT"
    assert result.error_message == "Python tool returned invalid JSON"


def test_worker_error_envelope_is_reported(monkeypatch) -> None:
    def errored(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise worker_error("ValueError: bad worker", "worker_error")

    monkeypatch.setattr(python_execution, "run_json_worker", errored)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "TOOL_FAILURE"
    assert result.error_message == "ValueError: bad worker"


def test_untrusted_message_text_does_not_choose_the_error_code(monkeypatch) -> None:
    def crashed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Python tool worker exited with -9: returned invalid JSON")

    monkeypatch.setattr(python_execution, "run_json_worker", crashed)

    result = LocalPythonTool().execute_batch(
        "def main():\n    return 1", "main", [{}], timeout_seconds=2
    )[0]

    assert result.error_code == "TOOL_FAILURE"


def test_wrong_result_count_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(
        python_execution,
        "run_json_worker",
        lambda *args, **kwargs: successful_response(),
    )

    results = LocalPythonTool().execute_batch(
        "def main():\n    return 1",
        "main",
        [{}, {}],
        timeout_seconds=2,
    )

    assert [result.error_code for result in results] == [
        "INVALID_TOOL_OUTPUT",
        "INVALID_TOOL_OUTPUT",
    ]


def test_untrusted_stderr_text_does_not_change_the_real_worker_error_code() -> None:
    code = (
        "import sys\n"
        "\n"
        "def main():\n"
        "    sys.stderr.write('worker exited with -9: returned invalid JSON\\n')\n"
        "    sys.stderr.flush()\n"
        "    raise SystemExit(3)\n"
    )

    result = LocalPythonTool().execute_batch(code, "main", [{}], timeout_seconds=10)[0]

    assert not result.ok
    assert result.error_code not in {"RESOURCE_LIMIT_EXCEEDED", "INVALID_TOOL_OUTPUT"}
    assert result.error_code == "TOOL_FAILURE"
