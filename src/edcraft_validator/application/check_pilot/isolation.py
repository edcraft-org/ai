"""Disposable-interpreter boundary for untrusted pilot symbolic work."""

from __future__ import annotations

import math
from typing import Any

from edcraft_validator.tools.isolated_process import run_json_worker

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
    return run_json_worker(
        payload,
        module=PILOT_WORKER_MODULE,
        timeout_seconds=timeout_seconds,
        timeout_error=PilotWorkerTimeout,
        worker_error=PilotWorkerError,
        description="pilot worker",
    )


__all__ = [
    "PILOT_WORKER_MODULE",
    "PilotWorkerError",
    "PilotWorkerTimeout",
    "run_pilot_isolated",
]
