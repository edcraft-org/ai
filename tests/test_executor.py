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
            "branch_executions": 0,
            "variable_snapshots": 1,
        },
    }
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(output), stderr="")


def test_runs_worker_with_container_isolation() -> None:
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


def test_timeout_force_removes_the_named_container() -> None:
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
        (137, "Killed", "RESOURCE_LIMIT_EXCEEDED"),
        (1, "Unexpected failure", "WORKER_FAILURE"),
    ],
)
def test_container_failures_are_classified(
    returncode: int, stderr: str, expected_code: str
) -> None:
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
    with pytest.raises(ValueError, match="greater than zero"):
        DockerExecutionConfig(**settings)
