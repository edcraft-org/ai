"""Domain-agnostic validation orchestration."""

import copy
import time
from collections.abc import Sequence

from edcraft_validator.models import ValidationIssue
from edcraft_validator.validation.contracts import (
    CheckResult,
    ValidationCheck,
    ValidationEvidence,
    ValidationFailure,
    ValidationPolicy,
    ValidationReport,
)


class ValidationPipeline:
    """Run named checks and retain consistent evidence for any domain."""

    def validate[ContextT](
        self,
        *,
        context: ContextT,
        checks: Sequence[ValidationCheck[ContextT]],
        policy: ValidationPolicy,
    ) -> ValidationReport:
        """Execute domain-supplied checks without interpreting the context."""
        names = [check.name for check in checks]
        if len(names) != len(set(names)):
            raise ValueError("validation check names must be unique")
        evidence: list[ValidationEvidence] = []
        failure = None
        for check in checks:
            started = time.perf_counter()
            try:
                result = check.run(context)
            except ValidationFailure as exc:
                result = CheckResult(status="failed", details=exc.context, failure=exc)
            except TimeoutError:
                result = CheckResult(
                    status="incomplete",
                    failure=ValidationFailure(
                        "Validation check timed out", code="CHECK_TIMEOUT"
                    ),
                )
            duration_ms = (time.perf_counter() - started) * 1000
            if result is None:
                continue
            if result.failure is not None and result.status == "passed":
                raise ValueError("a check with a failure cannot report success")
            issues = list(result.issues)
            if result.failure is not None:
                issues.append(
                    ValidationIssue(
                        code=result.failure.code,
                        message=str(result.failure),
                        field=result.failure.field,
                    )
                )
            evidence.append(
                ValidationEvidence(
                    check=check.name,
                    status=result.status,
                    assurance=check.assurance,
                    issues=issues,
                    details=copy.deepcopy(result.details),
                    duration_ms=duration_ms,
                )
            )
            if result.status != "passed" and (
                policy.stop_on_failure or check.name in policy.required_checks
            ):
                failure = (
                    failure
                    or result.failure
                    or ValidationFailure(
                        f"Validation check {check.name!r} {result.status}",
                        code="VALIDATION_INCOMPLETE"
                        if result.status == "incomplete"
                        else "VALIDATION_FAILED",
                    )
                )
                if policy.stop_on_failure:
                    break
        return ValidationReport(evidence=evidence, policy=policy, failure=failure)
