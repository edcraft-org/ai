"""JSON-only entry point for isolated math validation."""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from typing import Any

from edcraft_validator.domains.math.ir.schema import MathItemSpec, MathTemplateSpec
from edcraft_validator.domains.math.validation.harness import (
    Witness,
    validate_item,
    validate_template,
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        response = _run(payload)
    except Exception as exc:  # noqa: BLE001 - the boundary reports all failures
        json.dump(
            {"error": {"type": type(exc).__name__, "message": str(exc)}},
            sys.stdout,
        )
        return 0
    json.dump(response, sys.stdout, allow_nan=False)
    return 0


def _run(payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload.get("operation")
    witnesses = [Witness.model_validate(item) for item in payload.get("witnesses", [])]
    if operation == "validate_item":
        spec = MathItemSpec.model_validate(payload["spec"])
        params = _params(payload.get("params"))
        report = validate_item(
            spec,
            params=params,
            witnesses=witnesses,
            check_distractors=bool(payload.get("check_distractors", True)),
        )
        return {"report": report.model_dump(mode="json")}
    if operation == "validate_template":
        template = MathTemplateSpec.model_validate(payload["template"])
        report = validate_template(
            template,
            max_variants=int(payload.get("max_variants", 64)),
            witnesses=witnesses,
        )
        return {"report": report.model_dump(mode="json")}
    raise ValueError(f"unknown validation operation {operation!r}")


def _params(value: object) -> dict[str, Fraction] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("params must be an object")
    return {str(name): Fraction(str(amount)) for name, amount in value.items()}


if __name__ == "__main__":
    raise SystemExit(main())
