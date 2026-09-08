"""Domain-agnostic validation orchestration."""

import copy
import time
from collections.abc import Callable
from typing import Any, TypeVar

from edcraft_validator.models import ValidationIssue
from edcraft_validator.validation.contracts import (
    AssuranceLevel,
    ValidationEvidence,
    ValidationFailure,
)

ResultT = TypeVar("ResultT")


class ValidationPipeline:
    """Run named checks and retain consistent evidence for any domain."""

    def __init__(self) -> None:
        self.evidence: list[ValidationEvidence] = []

    def check(
        self,
        *,
        name: str,
        assurance: AssuranceLevel,
        details: dict[str, Any],
        operation: Callable[[], ResultT],
    ) -> ResultT:
        started = time.perf_counter()
        try:
            result = operation()
        except ValidationFailure as exc:
            failed_details = copy.deepcopy(details)
            failed_details.update(exc.context)
            self.evidence.append(
                ValidationEvidence(
                    check=name,
                    status="failed",
                    assurance=assurance,
                    issues=[
                        ValidationIssue(
                            code=exc.code,
                            message=str(exc),
                            field=exc.field,
                        )
                    ],
                    details=failed_details,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
            exc.evidence = copy.deepcopy(self.evidence)
            raise

        self.evidence.append(
            ValidationEvidence(
                check=name,
                status="passed",
                assurance=assurance,
                details=copy.deepcopy(details),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        )
        return result
