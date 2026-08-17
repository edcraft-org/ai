import json
from datetime import UTC, datetime
from pathlib import Path

from edcraft_validator.generation.models import GenerationAttempt, GenerationRequest


class JsonlAttemptLogger:
    """Append generation attempts in a format suitable for later evaluation."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def log(
        self,
        run_id: str,
        request: GenerationRequest,
        attempt: GenerationAttempt,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": run_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "request": request.model_dump(mode="json"),
            "attempt": attempt.model_dump(mode="json"),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, allow_nan=False) + "\n")
