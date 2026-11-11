"""Run one validation operation in a disposable interpreter.

SymPy has no cancellation API. A separate process gives a hard wall-clock limit
and isolates memory, while the data crossing the boundary stays JSON-only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

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
    serialized = json.dumps(payload, allow_nan=False)
    environment = dict(os.environ)
    environment.setdefault("PYTHONUNBUFFERED", "1")
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "edcraft_validator.domains.math.validation.worker",
            ],
            input=serialized,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationTimeout(
            f"math validation exceeded {timeout_seconds:g}s"
        ) from exc
    if completed.returncode != 0:
        raise ValidationWorkerError(
            f"validation worker exited with {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}"
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationWorkerError("validation worker returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise ValidationWorkerError("validation worker returned a non-object")
    if "error" in response:
        error = response["error"]
        raise ValidationWorkerError(
            f"{error.get('type', 'error')}: {error.get('message', '')}"
        )
    return response
