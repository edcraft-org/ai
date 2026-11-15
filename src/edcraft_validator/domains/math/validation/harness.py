"""Declarative validation harness for math IR items and templates.

The harness grades authored recipes and distractors through the engine and the
form registry, over a limited sample of the declared domain, before the
candidate is finalised.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict

from edcraft_validator.domains.math.engine_adapter import AdapterGap, grade
from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.instantiate import (
    compile_distractor_value,
    display_sympy_value,
    sample_parameter_combinations,
)
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    MathItemSpec,
    MathTemplateSpec,
)
from edcraft_validator.domains.math.math_types import (
    FORM_SENSITIVE_GOALS,
    MAX_IR_VARIANTS,
)
from edcraft_validator.domains.math.validation.answers import compile_answer_recipe
from edcraft_validator.domains.math.validation.distinct import same_value
from edcraft_validator.domains.math.validation.forms import check_form
from edcraft_validator.domains.math.validation.results import (
    CheckResult,
    CheckStatus,
    OptionCheck,
    ValidationReport,
)

MAX_VARIANTS = MAX_IR_VARIANTS

Aspect = Literal["correctness", "form"]


class HarnessReport(BaseModel):
    """One validation report plus the sampled coverage that produced it."""

    model_config = ConfigDict(extra="forbid", strict=True)

    report: ValidationReport
    checking_mode: Literal["property_based"] = "property_based"
    variants_checked: int = 0
    variants_total: int = 0
    seed: int = 0

    @property
    def passed(self) -> bool:
        return self.report.passed


def validate_item(
    spec: MathItemSpec,
    *,
    params: dict[str, Fraction] | None = None,
    aspect: Aspect = "correctness",
) -> HarnessReport:
    """Check one aspect of an authored item: its correctness or its form."""
    recipe = spec.answer_recipe
    if recipe is None:
        return _failed_harness_report(
            "the item declares no answer_recipe; nothing to grade"
        )
    try:
        declared = compile_answer_recipe(recipe, spec.symbols, params)
    except MathCompileError as exc:
        return _failed_harness_report(f"answer recipe does not compile: {exc}")

    if aspect == "form":
        checks = [_recipe_form(spec, recipe, params)]
        options = _check_distractor_forms(spec, params)
        option_findings = _failed_option_findings(options)
    else:
        checks = [_engine_correctness(spec, recipe, params)]
        options, option_findings = _check_recipe_distractors(spec, params)

    findings = _failed_check_findings(checks)
    findings.extend(option_findings)

    return _item_report(declared, checks, options, findings)


def _item_report(
    declared: object,
    checks: list[CheckResult],
    options: list[OptionCheck],
    findings: list[str],
) -> HarnessReport:
    """Combine the aspect's checks and options into one report."""
    return HarnessReport(
        report=ValidationReport(
            status=_aggregate(
                [
                    *[result.status for result in checks],
                    *[option.result.status for option in options],
                ]
            ),
            answer=display_sympy_value(declared),
            checks=checks,
            options=options,
            findings=findings,
        )
    )


def _failed_harness_report(
    message: str,
    *,
    variants_total: int = 0,
    seed: int = 0,
) -> HarnessReport:
    """Return a failed report for an input that cannot be checked."""
    return HarnessReport(
        report=ValidationReport(status="failed", findings=[message]),
        variants_total=variants_total,
        seed=seed,
    )


def _failed_check_findings(checks: list[CheckResult]) -> list[str]:
    return [
        f"{result.check}: {result.reason}"
        for result in checks
        if result.status == "failed" and result.reason
    ]


def _failed_option_findings(options: list[OptionCheck]) -> list[str]:
    return [
        f"option {option.index}: {option.result.reason}"
        for option in options
        if option.result.status == "failed"
    ]


def _engine_correctness(
    spec: MathItemSpec,
    answer: AnswerRecipe | Distractor,
    params: dict[str, Fraction] | None,
) -> CheckResult:
    """Ask the engine whether ``answer`` solves ``spec``; refusals fail closed."""
    try:
        grading = grade(spec, answer, params)
    except (AdapterGap, MathCompileError) as exc:
        return CheckResult(
            check="engine_correctness",
            status="failed",
            reason=f"the engine cannot grade this item: {exc}",
            evidence={"outcome": "unsupported", "expected": "correct"},
        )

    outcome = str(grading.outcome)
    passed = outcome == "correct"
    return CheckResult(
        check="engine_correctness",
        status="passed" if passed else "failed",
        reason="" if passed else f"the engine returned {outcome!r}: {grading.reason}",
        evidence={
            "outcome": outcome,
            "expected": "correct",
            "reason": grading.reason,
            "method": grading.method,
            "details": grading.details,
        },
    )


def _recipe_form(
    spec: MathItemSpec,
    answer: AnswerRecipe,
    params: dict[str, Fraction] | None,
) -> CheckResult:
    """Ask the form registry whether ``answer`` has the goal's required shape."""
    result = check_form(spec, answer, params)
    passed = result.status == "pass"
    return CheckResult(
        check="form",
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
    checks, compiled = _grade_distractors(spec, params)
    findings = _mark_duplicate_options(checks, compiled)
    return checks, findings


def _grade_distractors(
    spec: MathItemSpec,
    params: dict[str, Fraction] | None,
) -> tuple[list[OptionCheck], list[tuple[int, object]]]:
    """Grade every distractor and keep the values that compiled."""
    checks: list[OptionCheck] = []
    compiled: list[tuple[int, object]] = []
    for index, distractor in enumerate(spec.distractors):
        check, value = _distractor_option_check(spec, distractor, params, index)
        checks.append(check)
        if value is not None:
            compiled.append((index, value))
    return checks, compiled


def _distractor_option_check(
    spec: MathItemSpec,
    distractor: Distractor,
    params: dict[str, Fraction] | None,
    index: int,
) -> tuple[OptionCheck, object | None]:
    """Compile one distractor, then ask the engine to rule it out."""
    try:
        value = compile_distractor_value(spec, distractor, params)
    except MathCompileError:
        return _uncompiled_distractor_check(index, distractor), None

    grading = _engine_correctness(spec, distractor, params)
    status, reason = _distractor_verdict(grading)
    return (
        OptionCheck(
            index=index,
            value=display_sympy_value(value),
            misconception=distractor.misconception,
            result=CheckResult(
                check="distractor",
                status=status,
                reason=reason,
                evidence={"engine": grading.evidence},
            ),
        ),
        value,
    )


def _uncompiled_distractor_check(index: int, distractor: Distractor) -> OptionCheck:
    """Fail a distractor whose authored value does not compile."""
    return OptionCheck(
        index=index,
        value=_distractor_display(distractor),
        misconception=distractor.misconception,
        result=CheckResult(
            check="distractor",
            status="failed",
            reason="distractor value does not compile",
        ),
    )


def _distractor_verdict(grading: CheckResult) -> tuple[CheckStatus, str]:
    """Turn the engine's answer for a distractor into an option verdict."""
    outcome = str(grading.evidence.get("outcome", "error"))
    if grading.status == "passed":
        # The engine solved the problem with this option: it is the key.
        return "failed", "distractor answers the problem correctly"
    if outcome != "incorrect":
        return (
            "failed",
            f"could not prove the distractor wrong: engine returned {outcome!r}",
        )
    return "passed", "distractor is demonstrably wrong"


def _mark_duplicate_options(
    checks: list[OptionCheck],
    compiled: list[tuple[int, object]],
) -> list[str]:
    """Fail both options of every equivalent pair."""
    by_index = {check.index: check for check in checks}
    findings: list[str] = []
    for left in range(len(compiled)):
        for right in range(left + 1, len(compiled)):
            left_index, left_value = compiled[left]
            right_index, right_value = compiled[right]
            left_check = by_index[left_index]
            right_check = by_index[right_index]
            if not (
                same_value(left_value, right_value)
                or left_check.value == right_check.value
            ):
                continue
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
    return findings


def _check_distractor_forms(
    spec: MathItemSpec,
    params: dict[str, Fraction] | None,
) -> list[OptionCheck]:
    """Apply the key's form rule to distractors, for form-sensitive goals only.

    For every other goal an equivalent distractor is indistinguishable from
    the key, so a form rule on options would reject sound misconceptions.
    """
    if spec.goal.kind not in FORM_SENSITIVE_GOALS:
        return []

    checks: list[OptionCheck] = []
    for index, distractor in enumerate(spec.distractors):
        form = _recipe_form(spec, _recipe_from_distractor(distractor), params)
        checks.append(
            OptionCheck(
                index=index,
                value=_distractor_display(distractor),
                misconception=distractor.misconception,
                result=form.model_copy(
                    update={
                        "check": "distractor_form",
                        "reason": f"distractor form: {form.reason}"
                        if form.status == "failed"
                        else "",
                    }
                ),
            )
        )

    return checks


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
    seed: int = 0,
    aspect: Aspect = "correctness",
) -> HarnessReport:
    """Sample the declared domain. Any sampled failure blocks the template."""
    if template.body.answer_recipe is None:
        return _failed_harness_report(
            "template body must declare an answer_recipe; an answer "
            "cannot be derived for it"
        )
    sample = sample_parameter_combinations(template, limit=max_variants, seed=seed)

    if not sample.combinations:
        return _failed_harness_report(
            "template has no parameter combinations",
            variants_total=sample.declared_size,
            seed=seed,
        )

    reports = _variant_reports(template, sample.combinations, aspect)

    return HarnessReport(
        report=ValidationReport(
            status=_sampled_status(reports),
            answer=reports[0].report.answer if reports else "",
            checks=[item for report in reports for item in report.report.checks],
            options=[item for report in reports for item in report.report.options],
            findings=_variant_findings(reports),
        ),
        variants_checked=len(reports),
        variants_total=sample.declared_size,
        seed=seed,
    )


def _variant_reports(
    template: MathTemplateSpec,
    combinations: list[dict[str, Fraction]],
    aspect: Aspect,
) -> list[HarnessReport]:
    """Check each sampled parameter combination as one item."""
    return [
        validate_item(template.body, params=combination, aspect=aspect)
        for combination in combinations
    ]


def _variant_findings(reports: list[HarnessReport]) -> list[str]:
    """Prefix each failing variant's findings with its index."""
    findings: list[str] = []
    for index, report in enumerate(reports):
        if report.report.status != "passed":
            findings.extend(
                f"variant {index}: {finding}" for finding in report.report.findings
            )
    return findings


def _sampled_status(reports: list[HarnessReport]) -> CheckStatus:
    """A failure wins, then an inconclusive result, then a pass."""
    statuses = [report.report.status for report in reports]
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses:
        return "inconclusive"
    return "passed"


def _distractor_display(distractor: Distractor) -> str:
    return distractor.model_dump_json()


def _aggregate(statuses: list[CheckStatus]) -> CheckStatus:
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses or not statuses:
        return "inconclusive"
    return "passed"
