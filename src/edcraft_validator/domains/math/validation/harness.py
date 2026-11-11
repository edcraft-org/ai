"""Declarative validation harness for math IR items and templates.

The harness owns the *test*, not the topic. A topic generator emits a spec; the
harness derives the key, checks declared answers, rejects wrong witnesses and
sweeps template variants. A failed check blocks approval. An undecidable check
is reported as ``inconclusive`` and routes to review.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
)
from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Distractor,
    MathItemSpec,
    MathTemplateSpec,
)
from edcraft_validator.domains.math.ir.solve import (
    SolveUnavailable,
    solve_item,
)
from edcraft_validator.domains.math.validation.answers import compile_answer
from edcraft_validator.domains.math.validation.primitives import (
    expression_equiv,
    solution_set_equal,
)
from edcraft_validator.domains.math.validation.results import (
    OptionCheck,
    PrimitiveResult,
    PrimitiveStatus,
    ValidationReport,
)

MAX_VARIANTS = 64


class Witness(BaseModel):
    """A declared answer candidate that the harness must accept or reject."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    answer: Answer
    expected: Literal["accepted", "rejected"] = "accepted"


class WitnessOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    expected: Literal["accepted", "rejected"]
    observed: PrimitiveStatus
    passed: bool
    reason: str = ""


class HarnessReport(BaseModel):
    """Item report plus the witness outcomes that produced it."""

    model_config = ConfigDict(extra="forbid", strict=True)

    report: ValidationReport
    witnesses: list[WitnessOutcome] = Field(default_factory=list)
    variants_checked: int = 0

    @property
    def passed(self) -> bool:
        return self.report.passed and all(item.passed for item in self.witnesses)


def validate_item(
    spec: MathItemSpec,
    *,
    params: dict[str, Fraction] | None = None,
    witnesses: list[Witness] | None = None,
    check_distractors: bool = True,
) -> HarnessReport:
    """Solve, compare the declared key, and check option-level invariants."""
    findings: list[str] = []
    primitives: list[PrimitiveResult] = []
    options: list[OptionCheck] = []
    try:
        solved = solve_item(spec, params)
    except MathCompileError as exc:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=[f"IR does not compile: {exc}"],
            )
        )
    except SolveUnavailable as exc:
        return HarnessReport(
            report=ValidationReport(
                status="inconclusive",
                findings=[f"goal could not be decided: {exc}"],
            )
        )

    expected = solved.value
    derived_display = solved.answer.display

    if spec.answer is not None:
        try:
            declared = compile_answer(spec.answer, spec.symbols)
        except MathCompileError as exc:
            primitives.append(
                PrimitiveResult(
                    primitive="declared_answer",
                    status="failed",
                    reason=str(exc),
                )
            )
        else:
            checks = _check_all(spec, expected, declared)
            primitives.extend(checks)
            if any(check.status == "failed" for check in checks):
                findings.append("the declared answer contradicts the derived answer")
            elif checks and all(check.status == "inconclusive" for check in checks):
                findings.append("the declared answer could not be compared")

    if check_distractors and spec.distractors:
        option_checks, option_findings = _check_distractors(spec, expected, params)
        options.extend(option_checks)
        findings.extend(option_findings)

    witness_outcomes = []
    for witness in witnesses or []:
        outcome = _run_witness(spec, expected, witness)
        witness_outcomes.append(outcome)
        if not outcome.passed:
            findings.append(
                f"witness {witness.name!r} expected {witness.expected} "
                f"but observed {outcome.observed}"
            )

    status = _aggregate(
        [
            "passed",  # reaching here means the IR compiled and the goal solved
            *[check.status for check in primitives],
            *[option.result.status for option in options],
            *["passed" if item.passed else "failed" for item in witness_outcomes],
        ],
        findings,
    )
    return HarnessReport(
        report=ValidationReport(
            status=status,
            answer=derived_display,
            primitives=primitives,
            options=options,
            findings=findings,
        ),
        witnesses=witness_outcomes,
    )


def validate_template(
    template: MathTemplateSpec,
    *,
    max_variants: int = MAX_VARIANTS,
    witnesses: list[Witness] | None = None,
) -> HarnessReport:
    """Sweep a finite parameter grid; any failed variant blocks the template."""
    combinations = list(_parameter_combinations(template))
    if not combinations:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=["template has no parameter combinations"],
            )
        )
    if len(combinations) > max_variants:
        combinations = combinations[:max_variants]
    reports: list[HarnessReport] = []
    for combination in combinations:
        reports.append(
            validate_item(
                template.body,
                params=combination,
                witnesses=witnesses,
            )
        )
    merged_findings: list[str] = []
    failed = [report for report in reports if report.report.status == "failed"]
    inconclusive = [
        report for report in reports if report.report.status == "inconclusive"
    ]
    for index, report in enumerate(reports):
        if report.report.status != "passed":
            merged_findings.extend(
                f"variant {index}: {finding}" for finding in report.report.findings
            )
    if failed:
        status: PrimitiveStatus = "failed"
    elif inconclusive:
        status = "inconclusive"
    else:
        status = "passed"
    return HarnessReport(
        report=ValidationReport(
            status=status,
            answer=reports[0].report.answer if reports else "",
            primitives=[
                item for report in reports for item in report.report.primitives
            ],
            options=[item for report in reports for item in report.report.options],
            findings=merged_findings,
        ),
        witnesses=[item for report in reports for item in report.witnesses],
        variants_checked=len(reports),
    )


def check_answer(spec: MathItemSpec, candidate: Answer) -> PrimitiveResult:
    """Compare one candidate answer against the derived key."""
    try:
        solved = solve_item(spec)
    except (MathCompileError, SolveUnavailable) as exc:
        return PrimitiveResult(
            primitive="candidate",
            status="inconclusive",
            reason=str(exc),
        )
    try:
        compiled = compile_answer(candidate, spec.symbols)
    except MathCompileError as exc:
        return PrimitiveResult(
            primitive="candidate",
            status="failed",
            reason=str(exc),
        )
    results = _check_all(spec, solved.value, compiled)
    if any(result.status == "failed" for result in results):
        status: PrimitiveStatus = "failed"
        reason = "candidate differs from the derived key"
    elif results and all(result.status == "passed" for result in results):
        status = "passed"
        reason = "candidate matches the derived key"
    else:
        status = "inconclusive"
        reason = "no declared primitive could decide the candidate"
    return PrimitiveResult(
        primitive="candidate",
        status=status,
        reason=reason,
        evidence={"checks": [item.model_dump(mode="json") for item in results]},
    )


def _run_witness(
    spec: MathItemSpec,
    expected: object,
    witness: Witness,
) -> WitnessOutcome:
    try:
        compiled = compile_answer(witness.answer, spec.symbols)
    except MathCompileError as exc:
        observed: PrimitiveStatus = "failed"
        reason = str(exc)
    else:
        checks = _check_all(spec, expected, compiled)
        observed = _aggregate([check.status for check in checks], [])
        reason = "; ".join(check.reason for check in checks if check.reason)
    matched = (witness.expected == "accepted" and observed == "passed") or (
        witness.expected == "rejected" and observed == "failed"
    )
    return WitnessOutcome(
        name=witness.name,
        expected=witness.expected,
        observed=observed,
        passed=matched,
        reason=reason,
    )


def _check_all(
    spec: MathItemSpec,
    expected: object,
    actual: object,
) -> list[PrimitiveResult]:
    from edcraft_validator.domains.math.validation.primitives import (
        check_primitive,
    )

    symbols = list(build_symbols(spec.symbols).values())
    results = []
    for primitive in spec.validation.primitives:
        try:
            results.append(
                check_primitive(
                    primitive,
                    expected=expected,
                    actual=actual,
                    symbols=symbols,
                )
            )
        except (MathCompileError, TypeError, ValueError) as exc:
            results.append(
                PrimitiveResult(
                    primitive=primitive.type,
                    status="inconclusive",
                    reason=f"primitive cannot compare these values: {exc}",
                )
            )
    return results


def _check_distractors(
    spec: MathItemSpec,
    expected: object,
    params: dict[str, Fraction] | None = None,
) -> tuple[list[OptionCheck], list[str]]:
    findings: list[str] = []
    checks: list[OptionCheck] = []
    compiled: list[tuple[Distractor, object]] = []
    for index, distractor in enumerate(spec.distractors):
        value = _compile_distractor(spec, distractor, params)
        if value is None:
            checks.append(
                OptionCheck(
                    index=index,
                    value=_distractor_display(distractor),
                    misconception=distractor.misconception,
                    result=PrimitiveResult(
                        primitive="distractor",
                        status="failed",
                        reason="distractor value does not compile",
                    ),
                )
            )
            continue
        compiled.append((distractor, value))
        primitive_results = _check_all(spec, expected, value)
        rejected = any(result.status == "failed" for result in primitive_results)
        if all(result.status == "passed" for result in primitive_results):
            status: PrimitiveStatus = "failed"
            reason = "distractor is equivalent to the key"
        elif rejected:
            status = "passed"
            reason = "distractor is demonstrably wrong"
        else:
            status = "inconclusive"
            reason = "could not prove the distractor wrong"
        checks.append(
            OptionCheck(
                index=index,
                value=_distractor_display(distractor),
                misconception=distractor.misconception,
                result=PrimitiveResult(
                    primitive="distractor",
                    status=status,
                    reason=reason,
                ),
            )
        )

    for left_index in range(len(compiled)):
        for right_index in range(left_index + 1, len(compiled)):
            if _equivalent(compiled[left_index][1], compiled[right_index][1]):
                left = checks[left_index]
                right = checks[right_index]
                findings.append(
                    f"options {left.index} and {right.index} are equivalent"
                )
                checks[left.index].result = checks[left.index].result.model_copy(
                    update={
                        "status": "failed",
                        "reason": "duplicate distractor option",
                    }
                )
                checks[right.index].result = checks[right.index].result.model_copy(
                    update={
                        "status": "failed",
                        "reason": "duplicate distractor option",
                    }
                )
    return checks, findings


def _compile_distractor(
    spec: MathItemSpec,
    distractor: Distractor,
    params: dict[str, Fraction] | None = None,
) -> object | None:
    symbols = build_symbols(spec.symbols)
    values = params or {}
    try:
        if distractor.value is not None:
            return compile_expr(distractor.value, symbols, values)
        return [compile_expr(item, symbols, values) for item in distractor.items]
    except MathCompileError:
        return None


def _distractor_display(distractor: Distractor) -> str:
    if distractor.value is not None:
        return distractor.value.model_dump_json()
    return ",".join(item.model_dump_json() for item in distractor.items)


def _equivalent(left: object, right: object) -> bool:
    try:
        if expression_equiv(left, right).status == "passed":  # type: ignore[arg-type]
            return True
    except (TypeError, ValueError):
        pass
    try:
        return solution_set_equal(left, right).status == "passed"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _aggregate(
    statuses: list[PrimitiveStatus],
    findings: list[str],
) -> PrimitiveStatus:
    if "failed" in statuses or any(
        finding.startswith(("options ", "the declared answer contradicts"))
        for finding in findings
    ):
        return "failed"
    if "inconclusive" in statuses:
        return "inconclusive"
    if not statuses:
        return "inconclusive"
    return "passed"


def _parameter_combinations(
    template: MathTemplateSpec,
) -> list[dict[str, Fraction]]:
    names = [parameter.name for parameter in template.parameters]
    values = [parameter.values for parameter in template.parameters]
    combinations: list[dict[str, Fraction]] = []
    for combination in product(*values):
        try:
            combinations.append(
                dict(
                    zip(
                        names,
                        (Fraction(value) for value in combination),
                        strict=True,
                    )
                )
            )
        except (ValueError, ZeroDivisionError):
            continue
    return combinations


def report_payload(report: HarnessReport) -> dict[str, Any]:
    """Stable JSON payload for wire/tool responses."""
    return report.model_dump(mode="json")
