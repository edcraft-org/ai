"""One deterministic correctness check, isolated from application/model state."""

from __future__ import annotations

import math
import time
from typing import Any

from pydantic import ValidationError

from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
    EngineUnsupported,
)
from edcraft_validator.domains.math.engine.validation import validate_request
from edcraft_validator.tools.isolated_process import run_json_worker
from edcraft_validator.validation.check_contracts import (
    ToolEvidence,
    ToolFinding,
    ToolStatus,
)

TOOL_NAME = "math_check_correctness"
TOOL_VERSION = "1.0.0"
WORKER_MODULE = "edcraft_validator.domains.math.engine.worker"
DEFAULT_TIMEOUT_SECONDS = 10.0


class CorrectnessTimeout(TimeoutError):
    """A disposable symbolic computation exceeded its wall-clock budget."""


class CorrectnessWorkerError(RuntimeError):
    """The isolated worker did not return a usable computation result."""


def check_math_correctness(
    request: CorrectnessRequest | dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> CorrectnessResult:
    """Check one concrete answer without any model/provider calls."""
    if (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 60
    ):
        raise ValueError("timeout must be finite, positive and at most 60 seconds")
    started = time.perf_counter()
    try:
        raw = (
            request.model_dump(mode="json", warnings=False)
            if isinstance(request, CorrectnessRequest)
            else request
        )
        checked = CorrectnessRequest.model_validate(raw)
        validate_request(checked)
        response = run_json_worker(
            {"operation": "check", "request": checked.model_dump(mode="json")},
            module=WORKER_MODULE,
            timeout_seconds=timeout_seconds,
            timeout_error=CorrectnessTimeout,
            worker_error=CorrectnessWorkerError,
            description="math correctness",
        )
        result = CorrectnessResult.model_validate(response["result"])
    except EngineUnsupported as exc:
        result = CorrectnessResult(outcome="unsupported", reason=str(exc))
    except CorrectnessTimeout:
        result = CorrectnessResult(
            outcome="timeout", reason="symbolic calculation exceeded its time budget"
        )
    except (ValidationError, ValueError, TypeError, KeyError, RecursionError) as exc:
        result = CorrectnessResult(
            outcome="error", reason=f"invalid correctness request: {str(exc)[:500]}"
        )
    except CorrectnessWorkerError as exc:
        result = CorrectnessResult(
            outcome="error", reason=f"isolated calculation failed: {str(exc)[:500]}"
        )
    return result.model_copy(
        update={"duration_ms": (time.perf_counter() - started) * 1000}
    )


def correctness_evidence(result: CorrectnessResult) -> ToolEvidence:
    """Preserve unresolved outcomes inside the shared three-state transport."""
    status: ToolStatus = (
        "passed"
        if result.outcome == "correct"
        else "failed"
        if result.outcome == "incorrect"
        else "error"
    )
    return ToolEvidence(
        tool=TOOL_NAME,
        version=TOOL_VERSION,
        status=status,
        findings=[]
        if status == "passed"
        else [
            ToolFinding(code="MATH_" + result.outcome.upper(), message=result.reason)
        ],
        details=result.model_dump(mode="json"),
        duration_ms=result.duration_ms,
    )
