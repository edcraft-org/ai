"""Application facade for sampled deterministic correctness qualification."""

from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from edcraft_validator.application.math_correctness import (
    WORKER_MODULE,
    CorrectnessTimeout,
    CorrectnessWorkerError,
)
from edcraft_validator.domains.math.engine.contracts import EngineUnsupported
from edcraft_validator.domains.math.engine.sampling import (
    CorrectnessTemplate,
    SamplingSettings,
)
from edcraft_validator.tools.isolated_process import run_json_worker


def qualify_math_template(
    template: CorrectnessTemplate | dict[str, Any],
    *,
    settings: SamplingSettings | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    if (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 60
    ):
        raise ValueError(
            "qualification timeout must be finite, positive and at most 60 seconds"
        )
    try:
        raw = (
            template.model_dump(mode="json")
            if isinstance(template, CorrectnessTemplate)
            else template
        )
        definition = CorrectnessTemplate.model_validate(raw)
        selected = SamplingSettings.model_validate(
            (settings or SamplingSettings()).model_dump()
        )
        response = run_json_worker(
            {
                "operation": "qualify",
                "template": definition.model_dump(mode="json"),
                "settings": selected.model_dump(),
            },
            module=WORKER_MODULE,
            timeout_seconds=timeout_seconds,
            timeout_error=CorrectnessTimeout,
            worker_error=CorrectnessWorkerError,
            description="math correctness qualification",
        )
        return response["qualification"]
    except CorrectnessTimeout:
        return {
            "status": "timeout",
            "reason": "qualification timed out; partial results unavailable",
            "checking_mode": "property_based",
        }
    except (
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        EngineUnsupported,
        CorrectnessWorkerError,
    ) as exc:
        return {
            "status": "error",
            "reason": str(exc)[:500],
            "checking_mode": "property_based",
        }
