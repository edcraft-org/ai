"""Shared JSON-only process boundary for trusted worker modules.

The math validation and check-pilot workers own their operations and public
exception types. This module owns only the transport they share: a sanitized
environment, bounded JSON framing, a hard parent wall-clock timeout, resource
limits applied by a tiny trusted bootstrap, and safe failure mapping.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

try:  # pragma: no cover - the resource module is unavailable on Windows
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

BOOTSTRAP_MODULE = "edcraft_validator.tools.isolated_worker_bootstrap"
DEFAULT_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_STDERR_CHARS = 500
MAX_ERROR_MESSAGE_CHARS = 1000


class CodedWorkerError(RuntimeError):
    """Worker failure that may carry an explicit boundary error code.

    Subclassing opts an error type into receiving the worker's ``code`` field,
    so transport failures and untyped callers are unaffected.
    """

    code: str | None = None


_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_RUNTIME_ENVIRONMENT_NAMES = frozenset(
    {
        "LANG",
        "LANGUAGE",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "TEMP",
        "TMP",
        "TMPDIR",
    }
)
_ENVIRONMENT_PREFIXES = ("LC_",)
_WINDOWS_ENVIRONMENT_NAMES = frozenset({"COMSPEC", "PATHEXT", "SYSTEMROOT", "WINDIR"})


def worker_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return only interpreter/runtime inputs, never ambient credentials."""
    source = os.environ if environ is None else environ
    names = set(_RUNTIME_ENVIRONMENT_NAMES)
    if os.name == "nt":
        names.update(_WINDOWS_ENVIRONMENT_NAMES)
    environment = {name: source[name] for name in names if name in source}
    for name, value in source.items():
        if name.startswith(_ENVIRONMENT_PREFIXES):
            environment[name] = value
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    return environment


def validate_worker_module(module: str) -> str:
    """Reject non-module strings; callers still supply trusted constants."""
    if not isinstance(module, str) or _MODULE_NAME.fullmatch(module) is None:
        raise ValueError("isolated worker module name is invalid")
    return module


def cpu_limit_for_timeout(timeout_seconds: float) -> int:
    """Allow a small startup margin inside the parent wall-clock deadline."""
    return max(1, math.ceil(timeout_seconds) + 1)


def _inherited_limit(kind: int, requested: int) -> int:
    assert resource is not None
    soft, hard = resource.getrlimit(kind)
    infinity = getattr(resource, "RLIM_INFINITY", -1)
    candidates = [requested]
    if soft != infinity:
        candidates.append(int(soft))
    if hard != infinity:
        candidates.append(int(hard))
    return min(candidates)


def apply_resource_limits(
    *,
    cpu_seconds: int,
    memory_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
) -> dict[str, int]:
    """Apply hard limits without ever raising a tighter inherited cap."""
    if type(cpu_seconds) is not int or cpu_seconds <= 0:
        raise ValueError("worker CPU limit must be a positive integer")
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ValueError("worker memory limit must be a positive integer")
    applied: dict[str, int] = {}
    if resource is None:
        return applied
    if sys.platform.startswith("linux") and hasattr(resource, "RLIMIT_AS"):
        memory = _inherited_limit(resource.RLIMIT_AS, memory_bytes)
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        applied["memory_bytes"] = memory
    if hasattr(resource, "RLIMIT_CPU"):
        cpu = _inherited_limit(resource.RLIMIT_CPU, cpu_seconds)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        applied["cpu_seconds"] = cpu
    return applied


def run_json_worker(
    payload: dict[str, Any],
    *,
    module: str,
    timeout_seconds: float,
    timeout_error: type[TimeoutError],
    worker_error: type[RuntimeError],
    description: str,
    worker_description: str | None = None,
    cpu_seconds: int | None = None,
    memory_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
) -> dict[str, Any]:
    """Run one closed JSON request in a fresh interpreter with hard limits."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(f"{description} timeout must be finite and positive")
    selected_module = validate_worker_module(module)
    selected_cpu = (
        cpu_limit_for_timeout(timeout_seconds) if cpu_seconds is None else cpu_seconds
    )
    if type(selected_cpu) is not int or selected_cpu <= 0:
        raise ValueError("worker CPU limit must be a positive integer")
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ValueError("worker memory limit must be a positive integer")

    serialized = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"{description} payload exceeds the {MAX_PAYLOAD_BYTES}-byte limit"
        )

    worker_label = worker_description or description
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                BOOTSTRAP_MODULE,
                "--cpu-seconds",
                str(selected_cpu),
                "--memory-bytes",
                str(memory_bytes),
                selected_module,
            ],
            input=serialized,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=worker_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{description} exceeded {timeout_seconds:g}s") from exc
    if completed.returncode != 0:
        raise worker_error(
            f"{worker_label} exited with {completed.returncode}: "
            f"{completed.stderr.strip()[:MAX_STDERR_CHARS]}"
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise worker_error(f"{worker_label} returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise worker_error(f"{worker_label} returned a non-object")
    if "error" in response:
        error = response["error"]
        code = ""
        if isinstance(error, dict):
            error_type = str(error.get("type", "error"))[:100]
            message = str(error.get("message", ""))[:MAX_ERROR_MESSAGE_CHARS]
            code = str(error.get("code", ""))[:100]
        else:
            error_type = "error"
            message = str(error)[:MAX_ERROR_MESSAGE_CHARS]
        failure = worker_error(f"{error_type}: {message}")
        if code and isinstance(failure, CodedWorkerError):
            failure.code = code
        raise failure
    return response


__all__ = [
    "BOOTSTRAP_MODULE",
    "CodedWorkerError",
    "DEFAULT_MEMORY_LIMIT_BYTES",
    "MAX_PAYLOAD_BYTES",
    "apply_resource_limits",
    "cpu_limit_for_timeout",
    "run_json_worker",
    "validate_worker_module",
    "worker_environment",
]
