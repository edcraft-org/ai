"""Declarative validation harness for math IR items and templates.

The harness owns the *test*, not the topic. Authored recipe items are graded by
two independent oracles that are never collapsed into one field:

* ``engine_correctness`` -- the deterministic engine answers ``correct`` or the
  item is rejected, whatever the engine refused with;
* ``form`` -- the domain form registry says ``pass`` or the item is rejected.

An item passes only when both pass and every distractor is demonstrably wrong.
A failed check blocks approval. Validation samples the declared parameter domain
within a bounded budget, so a large authored domain never has to be materialised.
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
from edcraft_validator.domains.math.math_types import MAX_IR_VARIANTS
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

# Only these goals turn notation into mathematics. For every other goal an
# equivalent distractor is indistinguishable from the key, so applying the form
# rule to options would reject sound misconceptions.
FORM_SENSITIVE_GOALS = frozenset({"expand", "factor"})


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
) -> HarnessReport:
    """Grade an authored answer recipe, then prove every distractor wrong."""
    recipe = spec.answer_recipe
    if recipe is None:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=["the item declares no answer_recipe; nothing to grade"],
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

    checks = [
        _engine_correctness(spec, recipe, params),
        _recipe_form(spec, recipe, params),
    ]
    findings = [
        f"{result.check}: {result.reason}"
        for result in checks
        if result.status == "failed" and result.reason
    ]
    options, option_findings = _check_recipe_distractors(spec, params)
    findings.extend(option_findings)
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
                    result=CheckResult(
                        check="distractor",
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
            else CheckResult(check="form", status="passed")
        )
        if grading.status == "passed":
            # The engine solved the problem with this option: it is the key.
            status: CheckStatus = "failed"
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
                result=CheckResult(
                    check="distractor",
                    status=status,
                    reason=reason,
                    evidence={
                        "engine": grading.evidence,
                        "form": form.evidence or {"status": form.status},
                    },
                ),
            )
        )

    by_index = {check.index: check for check in checks}
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
    seed: int = 0,
) -> HarnessReport:
    """Sample the declared domain; any sampled failure blocks the template."""
    if template.body.answer_recipe is None:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=[
                    "template body must declare an answer_recipe; an answer "
                    "cannot be derived for it"
                ],
            )
        )
    sample = sample_parameter_combinations(template, limit=max_variants, seed=seed)
    if not sample.combinations:
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=["template has no parameter combinations"],
            ),
            variants_total=sample.declared_size,
            seed=seed,
        )
    reports: list[HarnessReport] = [
        validate_item(template.body, params=combination)
        for combination in sample.combinations
    ]
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
        status: CheckStatus = "failed"
    elif inconclusive:
        status = "inconclusive"
    else:
        status = "passed"
    return HarnessReport(
        report=ValidationReport(
            status=status,
            answer=reports[0].report.answer if reports else "",
            checks=[item for report in reports for item in report.report.checks],
            options=[item for report in reports for item in report.report.options],
            findings=merged_findings,
        ),
        variants_checked=len(reports),
        variants_total=sample.declared_size,
        seed=seed,
    )


def _distractor_display(distractor: Distractor) -> str:
    return distractor.model_dump_json()


def _aggregate(statuses: list[CheckStatus]) -> CheckStatus:
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses or not statuses:
        return "inconclusive"
    return "passed"
