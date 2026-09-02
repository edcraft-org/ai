import json
import subprocess
from unittest.mock import call, patch

import pytest

from edcraft_validator.executor import DockerExecutionConfig, DockerExecutor


def successful_process(answer: object = 16) -> subprocess.CompletedProcess[str]:
    output = {
        "ok": True,
        "answer": answer,
        "trace_summary": {
            "entry_function": "square",
            "function_calls": 1,
            "loop_executions": 0,
            "loop_iterations": 0,
            "branch_executions": 0,
            "variable_snapshots": 1,
        },
    }
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(output), stderr="")


def test_runs_worker_with_container_isolation() -> None:
    # The Docker command must preserve isolation while passing the request payload.
    executor = DockerExecutor()
    with patch(
        "edcraft_validator.executor.subprocess.run",
        return_value=successful_process(),
    ) as run:
        result = executor.execute(
            "def square(x):\n    return x * x",
            "square",
            {"x": 4},
            timeout_seconds=2,
        )

    command = run.call_args.args[0]
    payload = json.loads(run.call_args.kwargs["input"])
    assert result.ok
    assert result.answer == 16
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--memory=128m" in command
    assert "--memory-swap=128m" in command
    assert "--cpus=0.5" in command
    assert "--pids-limit=64" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert "--user=65532:65532" in command
    assert command[-1] == "edcraft-validator-executor:local"
    assert payload["inputs"] == {"x": 4}
    assert payload["timeout_seconds"] == 2
    assert run.call_args.kwargs["timeout"] == 12
    assert "def square" not in command


def test_runs_batch_in_one_container() -> None:
    output = {
        "ok": True,
        "results": [
            {"ok": True, "answer": 4, "trace_summary": {}},
            {"ok": True, "answer": 9, "trace_summary": {}},
        ],
    }
    process = subprocess.CompletedProcess([], 0, stdout=json.dumps(output), stderr="")
    with patch(
        "edcraft_validator.executor.subprocess.run", return_value=process
    ) as run:
        results = DockerExecutor().execute_batch(
            "def square(x):\n    return x * x",
            "square",
            [{"x": 2}, {"x": 3}],
            timeout_seconds=2,
        )

    payload = json.loads(run.call_args.kwargs["input"])
    assert run.call_count == 1
    assert payload["cases"] == [
        {"inputs": {"x": 2}},
        {"inputs": {"x": 3}},
    ]
    assert run.call_args.kwargs["timeout"] == 14
    assert [result.answer for result in results] == [4, 9]


def test_timeout_force_removes_the_named_container() -> None:
    # A timed-out container must be force-removed so no orphan can remain running.
    executor = DockerExecutor()
    timeout = subprocess.TimeoutExpired(["docker", "run"], 0.1)
    cleanup = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    with patch(
        "edcraft_validator.executor.subprocess.run",
        side_effect=[timeout, cleanup],
    ) as run:
        result = executor.execute(
            "def square(x):\n    return x * x",
            "square",
            {"x": 4},
            timeout_seconds=0.1,
        )

    container_name = run.call_args_list[0].args[0][4]
    assert result.error_code == "CONTAINER_TIMEOUT"
    assert run.call_args_list[1] == call(
        ["docker", "rm", "--force", container_name],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_missing_docker_executable_is_reported() -> None:
    # Missing local Docker should become an actionable structured error.
    executor = DockerExecutor()
    with patch(
        "edcraft_validator.executor.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        result = executor.execute(
            "def main():\n    return 1", "main", {}, timeout_seconds=2
        )

    assert result.error_code == "DOCKER_UNAVAILABLE"


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected_code"),
    [
        (125, "Error: No such image", "DOCKER_IMAGE_UNAVAILABLE"),
        (
            125,
            "error during connect: Docker daemon is not running",
            "DOCKER_UNAVAILABLE",
        ),
        (
            1,
            "permission denied while trying to connect to the Docker API",
            "DOCKER_UNAVAILABLE",
        ),
        (137, "Killed", "RESOURCE_LIMIT_EXCEEDED"),
        (1, "Unexpected failure", "WORKER_FAILURE"),
    ],
)
def test_container_failures_are_classified(
    returncode: int, stderr: str, expected_code: str
) -> None:
    # Common Docker failures need stable error codes for the service and CLI.
    process = subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)
    with patch("edcraft_validator.executor.subprocess.run", return_value=process):
        result = DockerExecutor().execute(
            "def main():\n    return 1", "main", {}, timeout_seconds=2
        )

    assert result.error_code == expected_code


@pytest.mark.parametrize(
    "settings",
    [
        {"cpus": 0},
        {"pids_limit": 0},
        {"startup_grace_seconds": 0},
    ],
)
def test_invalid_resource_limits_are_rejected(settings: dict[str, object]) -> None:
    # Invalid resource limits should fail during configuration, before execution.
    with pytest.raises(ValueError, match="greater than zero"):
        DockerExecutionConfig(**settings)


def test_invalid_worker_json_is_reported() -> None:
    # A successful container process is still invalid if it does not return JSON.
    process = subprocess.CompletedProcess([], 0, stdout="not-json", stderr="")
    with patch("edcraft_validator.executor.subprocess.run", return_value=process):
        result = DockerExecutor().execute(
            "def main():\n    return 1", "main", {}, timeout_seconds=2
        )

    assert result.error_code == "INVALID_WORKER_OUTPUT"
