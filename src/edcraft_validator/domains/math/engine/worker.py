"""JSON-only entry point for resource-limited deterministic math computation."""

from __future__ import annotations

import json
import sys

from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest
from edcraft_validator.domains.math.engine.dispatch import check_in_process


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("operation") == "check":
            result = check_in_process(
                CorrectnessRequest.model_validate(payload["request"])
            )
            response = {"result": result.model_dump(mode="json")}
        elif payload.get("operation") == "qualify":
            from edcraft_validator.domains.math.engine.sampling import (
                qualify_in_process,
            )

            response = {
                "qualification": qualify_in_process(
                    payload["template"], payload["settings"]
                )
            }
        else:
            raise ValueError("unknown worker operation")
    except Exception as exc:
        response = {"error": {"type": type(exc).__name__, "message": str(exc)[:500]}}
    json.dump(response, sys.stdout, allow_nan=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
