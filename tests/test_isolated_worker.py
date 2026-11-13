"""Shared JSON worker transport, failure mapping and resource-limit policy."""

from __future__ import annotations

import subprocess

import pytest

from edcraft_validator.application.check_pilot.isolation import (
    PILOT_WORKER_MODULE,
    PilotWorkerError,
    PilotWorkerTimeout,
    run_pilot_isolated,
)
from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.domains.math.validation.isolation import (
    ValidationTimeout,
    ValidationWorkerError,
    run_isolated,
)
from edcraft_validator.tools import isolated_process


def recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        steps=[
            RecipeStep(
                id="d1",
                operation="poly.differentiate",
                version="1",
                arguments={
                    "polynomial": RecipeArgument(source="input", name="problem")
                },
            ),
            RecipeStep(
                id="out",
                operation="poly.equivalent",
                version="1",
                arguments={
                    "expected": RecipeArgument(source="step", name="d1"),
                    "actual": RecipeArgument(source="input", name="candidate"),
                },
            ),
        ],
        output="out",
    )


def completed(
    returncode: int = 0, *, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_pilot_worker_real_json_roundtrip() -> None:
    response = run_pilot_isolated(
        {
            "operation": "execute_recipe",
            "definition": recipe().model_dump(mode="json"),
            "problem": "2*x + 3",
            "candidate": "2",
        },
        timeout_seconds=30,
    )

    assert response["result"]["verdict"] is True
    assert response["result"]["expected"] == "2"


def test_pilot_timeout_terminates_a_real_worker() -> None:
    with pytest.raises(PilotWorkerTimeout, match=r"exceeded 0\.01s"):
        run_pilot_isolated({"operation": "noop"}, timeout_seconds=0.01)


def test_math_timeout_terminates_a_real_worker() -> None:
    with pytest.raises(ValidationTimeout, match=r"exceeded 0\.01s"):
        run_isolated({"operation": "noop"}, timeout_seconds=0.01)


def test_pilot_error_envelope_is_mapped_safely() -> None:
    with pytest.raises(
        PilotWorkerError, match="ValueError: unknown pilot operation 'noop'"
    ):
        run_pilot_isolated({"operation": "noop"}, timeout_seconds=30)


def test_math_error_envelope_is_mapped_safely() -> None:
    with pytest.raises(
        ValidationWorkerError,
        match="ValueError: unknown validation operation 'noop'",
    ):
        run_isolated({"operation": "noop"}, timeout_seconds=30)


def test_nonzero_exit_is_mapped_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: completed(7, stderr="worker exploded\n"),
    )

    with pytest.raises(
        PilotWorkerError,
        match=r"pilot worker exited with 7: worker exploded",
    ):
        run_pilot_isolated({"operation": "noop"}, timeout_seconds=30)


def test_invalid_json_is_mapped_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: completed(stdout="{not json"),
    )

    with pytest.raises(ValidationWorkerError, match="returned invalid JSON"):
        run_isolated({"operation": "noop"}, timeout_seconds=30)


def test_non_object_response_is_mapped_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: completed(stdout="[]"),
    )

    with pytest.raises(ValidationWorkerError, match="returned a non-object"):
        run_isolated({"operation": "noop"}, timeout_seconds=30)


def test_malformed_error_envelope_is_mapped_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: completed(stdout='{"error": "bad worker"}'),
    )

    with pytest.raises(PilotWorkerError, match="error: bad worker"):
        run_pilot_isolated({"operation": "noop"}, timeout_seconds=30)


def test_worker_environment_keeps_runtime_inputs_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "fake-credential-sentinel-8d0a"
    monkeypatch.setenv("EDCRAFT_FAKE_API_KEY", sentinel)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example/db")
    monkeypatch.setenv("PATH", "/trusted/bin")
    monkeypatch.setenv("PYTHONPATH", "/worktree/src")
    monkeypatch.setenv("TMPDIR", "/tmp/worker")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")

    environment = isolated_process.worker_environment()

    assert environment["PATH"] == "/trusted/bin"
    assert environment["PYTHONPATH"] == "/worktree/src"
    assert environment["TMPDIR"] == "/tmp/worker"
    assert environment["LC_ALL"] == "C.UTF-8"
    assert environment["PYTHONUNBUFFERED"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert "EDCRAFT_FAKE_API_KEY" not in environment
    assert "DATABASE_URL" not in environment
    assert sentinel not in environment.values()


def test_subprocess_receives_the_sanitized_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "fake-credential-sentinel-5e2c"
    monkeypatch.setenv("EDCRAFT_FAKE_API_KEY", sentinel)
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        observed.update(kwargs)
        return completed(stdout="{}")

    monkeypatch.setattr(isolated_process.subprocess, "run", fake_run)

    assert run_pilot_isolated({"operation": "noop"}, timeout_seconds=30) == {}
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert "EDCRAFT_FAKE_API_KEY" not in environment
    assert sentinel not in environment.values()


def test_oversized_payload_is_rejected_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        nonlocal invoked
        invoked = True
        return completed(stdout="{}")

    monkeypatch.setattr(isolated_process.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="payload exceeds"):
        run_pilot_isolated(
            {"data": "x" * (isolated_process.MAX_PAYLOAD_BYTES + 1)},
            timeout_seconds=30,
        )
    assert invoked is False


pytestmark_resource = pytest.mark.skipif(
    isolated_process.resource is None,
    reason="resource module is unavailable on this platform",
)


@pytestmark_resource
def test_resource_limits_on_linux_include_memory_and_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = isolated_process.resource
    assert resource is not None
    calls: list[tuple[int, tuple[int, int]]] = []
    memory = 1024 * 1024 * 1024
    monkeypatch.setattr(isolated_process.sys, "platform", "linux")
    monkeypatch.setattr(
        isolated_process.resource,
        "getrlimit",
        lambda kind: (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
    )
    monkeypatch.setattr(
        isolated_process.resource,
        "setrlimit",
        lambda kind, limits: calls.append((kind, limits)),
    )

    applied = isolated_process.apply_resource_limits(cpu_seconds=5, memory_bytes=memory)

    assert applied == {"memory_bytes": memory, "cpu_seconds": 5}
    assert calls == [
        (resource.RLIMIT_AS, (memory, memory)),
        (resource.RLIMIT_CPU, (5, 5)),
    ]


@pytestmark_resource
def test_macos_does_not_claim_an_address_space_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = isolated_process.resource
    assert resource is not None
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(isolated_process.sys, "platform", "darwin")
    monkeypatch.setattr(
        isolated_process.resource,
        "getrlimit",
        lambda kind: (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
    )
    monkeypatch.setattr(
        isolated_process.resource,
        "setrlimit",
        lambda kind, limits: calls.append((kind, limits)),
    )

    applied = isolated_process.apply_resource_limits(
        cpu_seconds=5, memory_bytes=1024 * 1024 * 1024
    )

    assert applied == {"cpu_seconds": 5}
    assert calls == [(resource.RLIMIT_CPU, (5, 5))]


@pytestmark_resource
def test_resource_limits_respect_tighter_inherited_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = isolated_process.resource
    assert resource is not None
    calls: list[tuple[int, tuple[int, int]]] = []
    memory = 256 * 1024 * 1024

    def inherited(kind: int) -> tuple[int, int]:
        if kind == resource.RLIMIT_AS:
            return (memory, 512 * 1024 * 1024)
        return (1, 2)

    monkeypatch.setattr(isolated_process.sys, "platform", "linux")
    monkeypatch.setattr(isolated_process.resource, "getrlimit", inherited)
    monkeypatch.setattr(
        isolated_process.resource,
        "setrlimit",
        lambda kind, limits: calls.append((kind, limits)),
    )

    isolated_process.apply_resource_limits(
        cpu_seconds=10, memory_bytes=1024 * 1024 * 1024
    )

    assert calls == [
        (resource.RLIMIT_AS, (memory, memory)),
        (resource.RLIMIT_CPU, (1, 1)),
    ]


def test_pilot_module_name_stays_an_application_constant() -> None:
    assert PILOT_WORKER_MODULE == "edcraft_validator.application.check_pilot.worker"
    assert isolated_process.BOOTSTRAP_MODULE == (
        "edcraft_validator.tools.isolated_worker_bootstrap"
    )
