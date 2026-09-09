import json
import subprocess
import sys
from unittest.mock import patch

from edcraft_validator.tools.python_execution import LocalPythonTool


def successful_process(answer: object = 16) -> subprocess.CompletedProcess[str]:
    output = {
        "ok": True,
        "results": [
            {
                "ok": True,
                "answer": answer,
                "trace_summary": {"entry_function": "square"},
            }
        ],
    }
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(output), stderr="")


def test_runs_packaged_python_tool(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-worker")
    with patch(
        "edcraft_validator.tools.python_execution.subprocess.run",
        return_value=successful_process(),
    ) as run:
        result = LocalPythonTool().execute_batch(
            "def square(x):\n    return x * x",
            "square",
            [{"x": 4}],
            timeout_seconds=2,
        )[0]

    assert result.ok
    assert result.answer == 16
    assert run.call_args.args[0] == [
        sys.executable,
        "-m",
        "edcraft_validator.tools.python_worker",
    ]
    payload = json.loads(run.call_args.kwargs["input"])
    assert payload["cases"] == [{"inputs": {"x": 4}}]
    assert payload["timeout_seconds"] == 2
    assert "OPENAI_API_KEY" not in run.call_args.kwargs["env"]


def test_runs_batch_in_one_subprocess() -> None:
    process = subprocess.CompletedProcess(
        [],
        0,
        stdout=json.dumps(
            {
                "ok": True,
                "results": [
                    {"ok": True, "answer": 4, "trace_summary": {}},
                    {"ok": True, "answer": 9, "trace_summary": {}},
                ],
            }
        ),
        stderr="",
    )
    with patch(
        "edcraft_validator.tools.python_execution.subprocess.run",
        return_value=process,
    ) as run:
        results = LocalPythonTool().execute_batch(
            "def square(x):\n    return x * x",
            "square",
            [{"x": 2}, {"x": 3}],
            timeout_seconds=2,
        )

    assert run.call_count == 1
    payload = json.loads(run.call_args.kwargs["input"])
    assert payload["cases"] == [
        {"inputs": {"x": 2}},
        {"inputs": {"x": 3}},
    ]
    assert [result.answer for result in results] == [4, 9]


def test_timeout_is_reported() -> None:
    with patch(
        "edcraft_validator.tools.python_execution.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["python"], 0.1),
    ):
        result = LocalPythonTool().execute_batch(
            "def main():\n    return 1", "main", [{}], timeout_seconds=0.1
        )[0]

    assert result.error_code == "EXECUTION_TIMEOUT"


def test_process_failure_is_reported() -> None:
    process = subprocess.CompletedProcess([], 1, stdout="", stderr="worker failed")
    with patch(
        "edcraft_validator.tools.python_execution.subprocess.run",
        return_value=process,
    ):
        result = LocalPythonTool().execute_batch(
            "def main():\n    return 1", "main", [{}], timeout_seconds=2
        )[0]

    assert result.error_code == "TOOL_FAILURE"
    assert result.error_message == "worker failed"


def test_process_killed_by_resource_limit_is_reported() -> None:
    process = subprocess.CompletedProcess([], -9, stdout="", stderr="")
    with patch(
        "edcraft_validator.tools.python_execution.subprocess.run",
        return_value=process,
    ):
        result = LocalPythonTool().execute_batch(
            "def main():\n    return 1", "main", [{}], timeout_seconds=2
        )[0]

    assert result.error_code == "RESOURCE_LIMIT_EXCEEDED"


def test_invalid_worker_json_is_reported() -> None:
    process = subprocess.CompletedProcess([], 0, stdout="not-json", stderr="")
    with patch(
        "edcraft_validator.tools.python_execution.subprocess.run",
        return_value=process,
    ):
        result = LocalPythonTool().execute_batch(
            "def main():\n    return 1", "main", [{}], timeout_seconds=2
        )[0]

    assert result.error_code == "INVALID_TOOL_OUTPUT"
