import json
from datetime import UTC, datetime
from pathlib import Path

from edcraft_validator.generation.models import GenerationAttempt, GenerationRequest
from edcraft_validator.generation.observability import AttemptTelemetry


class JsonlAttemptLogger:
    """Append generation attempts in a format suitable for later evaluation."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def log(
        self,
        run_id: str,
        request: GenerationRequest,
        attempt: GenerationAttempt,
        telemetry: AttemptTelemetry,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": run_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "request": request.model_dump(mode="json"),
            "attempt": attempt.model_dump(mode="json"),
            "telemetry": {
                "provider": telemetry.provider,
                "model": telemetry.model,
                "generation_duration_ms": telemetry.generation_duration_ms,
                "validation_duration_ms": telemetry.validation_duration_ms,
                "status": telemetry.status,
                "issue_codes": list(telemetry.issue_codes),
            },
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, allow_nan=False) + "\n")
