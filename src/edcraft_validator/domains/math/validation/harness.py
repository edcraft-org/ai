"""Declarative validation harness for math IR items and templates.

The harness owns the *test*, not the topic. Authored recipe items are graded by
two independent oracles that are never collapsed into one field:

* ``engine_correctness`` -- the deterministic engine answers ``correct`` or the
  item is rejected, whatever the engine refused with;
* ``form`` -- the domain form registry says ``pass`` or the item is rejected.

An item passes only when both pass. Items that still carry a derived key (topic
generators) are checked against the solver output as before. A failed check
blocks approval; an undecidable check is reported as ``inconclusive`` and
routes to review.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.domains.math.engine_adapter import AdapterGap, grade
from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
)
from edcraft_validator.domains.math.ir.instantiate import (
    compile_distractor_value,
    display_distractor,
    display_sympy_value,
    parameter_combinations,
)
from edcraft_validator.domains.math.ir.schema import (
    Answer,
    AnswerRecipe,
    Distractor,
    MathItemSpec,
    MathTemplateSpec,
)
from edcraft_validator.domains.math.ir.solve import (
    SolveUnavailable,
    solve_item,
)
from edcraft_validator.domains.math.validation.answers import (
    compile_answer,
    compile_answer_recipe,
)
from edcraft_validator.domains.math.validation.forms import check_form
from edcraft_validator.domains.math.validation.primitives import (
    option_equivalent,
)
from edcraft_validator.domains.math.validation.results import (
    OptionCheck,
    PrimitiveResult,
    PrimitiveStatus,
    ValidationReport,
)

MAX_VARIANTS = 64

# Only these goals turn notation into mathematics. For every other goal an
# equivalent distractor is indistinguishable from the key, so applying the form
# rule to options would reject sound misconceptions.
FORM_SENSITIVE_GOALS = frozenset({"expand", "factor"})


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
    variants_total: int = 0

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
    """Grade an authored recipe, or compare a derived key, then check options."""
    if spec.answer_recipe is not None:
        return _validate_recipe_item(
            spec,
            params=params,
            witnesses=witnesses,
            check_distractors=check_distractors,
        )
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
        ]
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


def _validate_recipe_item(
    spec: MathItemSpec,
    *,
    params: dict[str, Fraction] | None,
    witnesses: list[Witness] | None,
    check_distractors: bool,
) -> HarnessReport:
    """Grade one authored recipe with the engine and the form registry.

    The recipe is the answer: nothing here derives a key with the solver, so a
    model that authors a wrong answer is rejected instead of being corrected.
    """
    recipe = spec.answer_recipe
    if recipe is None:  # pragma: no cover - guarded by validate_item
        raise ValueError("recipe validation requires an answer_recipe")
    if spec.answer is not None:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=[
                    "an item declares either a derived answer or an answer recipe, "
                    "never both"
                ],
            )
        )
    try:
        declared = compile_answer_recipe(recipe, spec.symbols, params)
    except MathCompileError as exc:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=[f"answer recipe does not compile: {exc}"],
            )
        )

    primitives = [
        _engine_correctness(spec, recipe, params),
        _recipe_form(spec, recipe, params),
    ]
    findings = [
        f"{result.primitive}: {result.reason}"
        for result in primitives
        if result.status == "failed" and result.reason
    ]
    options: list[OptionCheck] = []
    if check_distractors and spec.distractors:
        option_checks, option_findings = _check_recipe_distractors(spec, params)
        options.extend(option_checks)
        findings.extend(option_findings)

    witness_outcomes = []
    for witness in witnesses or []:
        outcome = _run_witness(spec, declared, witness)
        witness_outcomes.append(outcome)
        if not outcome.passed:
            findings.append(
                f"witness {witness.name!r} expected {witness.expected} "
                f"but observed {outcome.observed}"
            )

    return HarnessReport(
        report=ValidationReport(
            status=_aggregate(
                [
                    *[result.status for result in primitives],
                    *[option.result.status for option in options],
                    *[
                        "passed" if item.passed else "failed"
                        for item in witness_outcomes
                    ],
                ]
            ),
            answer=display_sympy_value(declared),
            primitives=primitives,
            options=options,
            findings=findings,
        ),
        witnesses=witness_outcomes,
    )


def _engine_correctness(
    spec: MathItemSpec,
    answer: AnswerRecipe | Distractor,
    params: dict[str, Fraction] | None,
) -> PrimitiveResult:
    """Ask the engine whether ``answer`` solves ``spec``; refusals fail closed."""
    try:
        grading = grade(spec, answer, params)
    except (AdapterGap, MathCompileError) as exc:
        return PrimitiveResult(
            primitive="engine_correctness",
            status="failed",
            reason=f"the engine cannot grade this item: {exc}",
            evidence={"outcome": "unsupported", "expected": "correct"},
        )
    outcome = str(grading.outcome)
    passed = outcome == "correct"
    return PrimitiveResult(
        primitive="engine_correctness",
        status="passed" if passed else "failed",
        reason="" if passed else f"the engine returned {outcome!r}",
        evidence={"outcome": outcome, "expected": "correct"},
    )


def _recipe_form(
    spec: MathItemSpec,
    answer: AnswerRecipe,
    params: dict[str, Fraction] | None,
) -> PrimitiveResult:
    """Ask the form registry whether ``answer`` has the goal's required shape."""
    result = check_form(spec, answer, params)
    passed = result.status == "pass"
    return PrimitiveResult(
        primitive="form",
        status="passed" if passed else "failed",
        reason=""
        if passed
        else result.reason or f"form check returned {result.status}",
        evidence={"status": result.status, "expected": "pass"},
    )


def _check_recipe_distractors(
    spec: MathItemSpec,
    params: dict[str, Fraction] | None,
) -> tuple[list[OptionCheck], list[str]]:
    """Every authored distractor must be demonstrably wrong, per variant."""
    findings: list[str] = []
    checks: list[OptionCheck] = []
    compiled: list[tuple[int, object]] = []
    form_sensitive = spec.goal.kind in FORM_SENSITIVE_GOALS
    for index, distractor in enumerate(spec.distractors):
        try:
            value = compile_distractor_value(spec, distractor, params)
        except MathCompileError:
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
        compiled.append((index, value))
        grading = _engine_correctness(spec, distractor, params)
        outcome = str(grading.evidence.get("outcome", "error"))
        form = (
            _recipe_form(spec, _recipe_from_distractor(distractor), params)
            if form_sensitive
            else PrimitiveResult(primitive="form", status="passed")
        )
        if grading.status == "passed":
            # The engine solved the problem with this option: it is the key.
            status: PrimitiveStatus = "failed"
            reason = "distractor answers the problem correctly"
        elif outcome != "incorrect":
            status = "failed"
            reason = (
                f"could not prove the distractor wrong: engine returned {outcome!r}"
            )
        elif form.status == "failed":
            status = "failed"
            reason = f"distractor form: {form.reason}"
        else:
            status = "passed"
            reason = "distractor is demonstrably wrong"
        checks.append(
            OptionCheck(
                index=index,
                value=display_sympy_value(value),
                misconception=distractor.misconception,
                result=PrimitiveResult(
                    primitive="distractor",
                    status=status,
                    reason=reason,
                    evidence={
                        "engine": grading.evidence,
                        "form": form.evidence or {"status": form.status},
                    },
                ),
            )
        )

    for left in range(len(compiled)):
        for right in range(left + 1, len(compiled)):
            if _equivalent(compiled[left][1], compiled[right][1]):
                left_check = checks[compiled[left][0]]
                right_check = checks[compiled[right][0]]
                findings.append(
                    f"options {left_check.index} and {right_check.index} are equivalent"
                )
                for check in (left_check, right_check):
                    check.result = check.result.model_copy(
                        update={
                            "status": "failed",
                            "reason": "duplicate distractor option",
                        }
                    )
    return checks, findings


def _recipe_from_distractor(distractor: Distractor) -> AnswerRecipe:
    """Project a distractor onto the answer kinds the form registry understands."""
    if distractor.value is not None:
        return AnswerRecipe(kind="expression", items=[distractor.value])
    if distractor.components:
        return AnswerRecipe(kind="tuple", items=list(distractor.components))
    return AnswerRecipe(kind="set", items=list(distractor.items))


def validate_template(
    template: MathTemplateSpec,
    *,
    max_variants: int = MAX_VARIANTS,
    witnesses: list[Witness] | None = None,
) -> HarnessReport:
    """Sweep a finite parameter grid; any failed variant blocks the template."""
    if template.body.answer_recipe is None:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=[
                    "template body must declare an answer_recipe; the solver no "
                    "longer supplies template answers"
                ],
            )
        )
    combinations = list(_parameter_combinations(template))
    total_variants = len(combinations)
    if not combinations:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=["template has no parameter combinations"],
            )
        )
    truncated = total_variants > max_variants
    if truncated:
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
    elif inconclusive or truncated:
        status = "inconclusive"
    else:
        status = "passed"
    if truncated:
        merged_findings.append(
            f"variant sweep truncated to {len(combinations)} of "
            f"{total_variants} combinations"
        )
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
        variants_total=total_variants,
    )


def check_answer(
    spec: MathItemSpec,
    candidate: Answer,
    *,
    params: dict[str, Fraction] | None = None,
) -> PrimitiveResult:
    """Compare one candidate answer against the key."""
    if spec.answer_recipe is not None:
        try:
            expected = compile_answer_recipe(spec.answer_recipe, spec.symbols, params)
        except MathCompileError as exc:
            return PrimitiveResult(
                primitive="candidate",
                status="inconclusive",
                reason=f"the answer recipe does not compile: {exc}",
            )
    else:
        try:
            expected = solve_item(spec).value
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
    results = _check_all(spec, expected, compiled)
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
        observed = _aggregate([check.status for check in checks])
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
        display = (
            display_distractor(spec, distractor, params)
            if value is not None
            else _distractor_display(distractor)
        )
        if value is None:
            checks.append(
                OptionCheck(
                    index=index,
                    value=display,
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
        collision = option_equivalent(expected, value)
        rejected = any(result.status == "failed" for result in primitive_results)
        if collision.status == "passed" or all(
            result.status == "passed" for result in primitive_results
        ):
            # The declared primitives may be unable to compare this option's
            # type, so a direct value comparison also guards the key.
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
                value=display,
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
    try:
        return compile_distractor_value(spec, distractor, params)
    except MathCompileError:
        return None


def _distractor_display(distractor: Distractor) -> str:
    return distractor.model_dump_json()


def _equivalent(left: object, right: object) -> bool:
    return option_equivalent(left, right).status == "passed"


def _aggregate(statuses: list[PrimitiveStatus]) -> PrimitiveStatus:
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses or not statuses:
        return "inconclusive"
    return "passed"


def _parameter_combinations(
    template: MathTemplateSpec,
) -> list[dict[str, Fraction]]:
    return parameter_combinations(template)
