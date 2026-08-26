import json
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_EXECUTOR_IMAGE = "edcraft-validator-executor:local"


@dataclass
class ExecutionResult:
    ok: bool
    answer: Any | None = None
    trace_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class ExecutionBackend(Protocol):
    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult: ...


@dataclass(frozen=True)
class DockerExecutionConfig:
    image: str = DEFAULT_EXECUTOR_IMAGE
    executable: str = "docker"
    memory: str = "128m"
    cpus: float = 0.5
    pids_limit: int = 64
    temporary_storage: str = "16m"
    startup_grace_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.cpus <= 0:
            raise ValueError("cpus must be greater than zero")
        if self.pids_limit <= 0:
            raise ValueError("pids_limit must be greater than zero")
        if self.startup_grace_seconds <= 0:
            raise ValueError("startup_grace_seconds must be greater than zero")


class DockerExecutor:
    """Execute the tracing worker inside a restricted, disposable container."""

    def __init__(self, config: DockerExecutionConfig | None = None) -> None:
        self.config = config or DockerExecutionConfig()

    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        payload = json.dumps(
            {
                "code": code,
                "entry_function": entry_function,
                "inputs": inputs,
                "timeout_seconds": timeout_seconds,
            },
            allow_nan=False,
        )
        container_name = f"edcraft-validator-{uuid.uuid4().hex}"
        command = self._build_command(container_name)

        try:
            process = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + self.config.startup_grace_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._remove_container(container_name)
            return ExecutionResult(
                ok=False,
                error_code="CONTAINER_TIMEOUT",
                error_message=(
                    "Docker did not finish within the execution timeout and "
                    "startup allowance"
                ),
            )
        except FileNotFoundError:
            return ExecutionResult(
                ok=False,
                error_code="DOCKER_UNAVAILABLE",
                error_message="Docker is not installed or is not available on PATH",
            )

        if process.returncode != 0:
            return self._docker_failure(process)

        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError:
            return ExecutionResult(
                ok=False,
                error_code="INVALID_WORKER_OUTPUT",
                error_message="Execution container returned invalid JSON",
            )

        return ExecutionResult(
            ok=result["ok"],
            answer=result.get("answer"),
            trace_summary=result.get("trace_summary"),
            error_code=result.get("error_code"),
            error_message=result.get("error_message"),
        )

    def _build_command(self, container_name: str) -> list[str]:
        config = self.config
        return [
            config.executable,
            "run",
            "--rm",
            "--name",
            container_name,
            "--interactive",
            "--pull=never",
            "--network=none",
            "--read-only",
            f"--memory={config.memory}",
            f"--memory-swap={config.memory}",
            f"--cpus={config.cpus:g}",
            f"--pids-limit={config.pids_limit}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65532:65532",
            f"--tmpfs=/tmp:rw,noexec,nosuid,size={config.temporary_storage}",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            config.image,
        ]

    def _remove_container(self, container_name: str) -> None:
        try:
            subprocess.run(
                [self.config.executable, "rm", "--force", container_name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _docker_failure(process: subprocess.CompletedProcess[str]) -> ExecutionResult:
        message = process.stderr.strip() or "Execution container exited unexpectedly"
        lowered = message.lower()
        if process.returncode in (137, 143):
            code = "RESOURCE_LIMIT_EXCEEDED"
        elif "no such image" in lowered or "unable to find image" in lowered:
            code = "DOCKER_IMAGE_UNAVAILABLE"
        elif "docker daemon" in lowered or "error during connect" in lowered:
            code = "DOCKER_UNAVAILABLE"
        else:
            code = "WORKER_FAILURE"
        return ExecutionResult(
            ok=False,
            error_code=code,
            error_message=message[-1000:],
        )


def execute_with_tracer(
    code: str,
    entry_function: str,
    inputs: dict[str, Any],
    *,
    timeout_seconds: float = 2.0,
) -> ExecutionResult:
    """Backward-compatible wrapper around the Docker execution backend."""
    return DockerExecutor().execute(
        code,
        entry_function,
        inputs,
        timeout_seconds=timeout_seconds,
    )
