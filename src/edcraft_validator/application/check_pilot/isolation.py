"""Disposable-interpreter boundary for untrusted pilot symbolic work."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from typing import Any

PILOT_WORKER_MODULE = "edcraft_validator.application.check_pilot.worker"


class PilotWorkerTimeout(TimeoutError):
    """The isolated pilot worker exceeded its hard wall-clock deadline."""


class PilotWorkerError(RuntimeError):
    """The isolated pilot worker failed before returning a report."""


def run_pilot_isolated(
    payload: dict[str, Any], *, timeout_seconds: float
) -> dict[str, Any]:
    """Run one closed JSON request in a fresh interpreter with a hard limit."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("pilot worker timeout must be finite and positive")
    serialized = json.dumps(payload, allow_nan=False)
    environment = dict(os.environ)
    environment.setdefault("PYTHONUNBUFFERED", "1")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", PILOT_WORKER_MODULE],
            input=serialized,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PilotWorkerTimeout(f"pilot worker exceeded {timeout_seconds:g}s") from exc
    if completed.returncode != 0:
        raise PilotWorkerError(
            f"pilot worker exited with {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}"
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PilotWorkerError("pilot worker returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise PilotWorkerError("pilot worker returned a non-object")
    if "error" in response:
        error = response["error"]
        raise PilotWorkerError(
            f"{error.get('type', 'error')}: {error.get('message', '')}"
        )
    return response


__all__ = [
    "PILOT_WORKER_MODULE",
    "PilotWorkerError",
    "PilotWorkerTimeout",
    "run_pilot_isolated",
]
