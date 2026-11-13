"""Run one validation operation in a disposable interpreter.

SymPy has no cancellation API. A separate process gives a hard wall-clock limit
and isolates memory, while the data crossing the boundary stays JSON-only.
"""

from __future__ import annotations

from typing import Any

from edcraft_validator.tools.isolated_process import run_json_worker

WORKER_MODULE = "edcraft_validator.domains.math.validation.worker"
DEFAULT_VALIDATION_TIMEOUT_SECONDS = 20.0


class ValidationTimeout(TimeoutError):
    """The isolated validation worker exceeded its deadline."""


class ValidationWorkerError(RuntimeError):
    """The isolated worker failed before producing a report."""


def run_isolated(
    payload: dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_VALIDATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("validation timeout must be positive")
    return run_json_worker(
        payload,
        module=WORKER_MODULE,
        timeout_seconds=timeout_seconds,
        timeout_error=ValidationTimeout,
        worker_error=ValidationWorkerError,
        description="math validation",
        worker_description="validation worker",
    )


__all__ = [
    "DEFAULT_VALIDATION_TIMEOUT_SECONDS",
    "ValidationTimeout",
    "ValidationWorkerError",
    "WORKER_MODULE",
    "run_isolated",
]
