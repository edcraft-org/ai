"""Declarative validation harness for math IR items and templates.

The harness grades authored recipes before the candidate is finalised. It has two
independent aspects, each requested separately. ``correctness`` asks the engine
to grade the key correct and every distractor incorrect, with no two options
sharing a value. ``form`` asks the form registry whether the key has the shape
its goal demands, and form-sensitive goals apply the same rule to distractors.
Neither aspect implies the other. Validation checks the declared parameter
domain through the shared Hypothesis property checker, with explicit boundary
examples and exhaustive coverage of small domains.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Literal

from hypothesis import assume
from hypothesis.errors import Unsatisfiable
from pydantic import BaseModel, ConfigDict

from edcraft_validator.domains.math.engine_adapter import AdapterGap, grade
from edcraft_validator.domains.math.ir.compile import MathCompileError
from edcraft_validator.domains.math.ir.instantiate import (
    compile_distractor_value,
    declared_domain_size,
    display_sympy_value,
    fraction_text,
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
from edcraft_validator.validation.property_checks import (
    PropertyCheckRun,
    PropertyCheckSettings,
)
from edcraft_validator.validation.property_summary import property_details
from edcraft_validator.validation.validation_contracts import ValidationFailure

MAX_VARIANTS = MAX_IR_VARIANTS

# A property-check deadline that stays inside the default 20 s worker deadline.
PROPERTY_CHECK_TIMEOUT_SECONDS = 15.0

_VARIANT_FAILED = "MATH_VARIANT_FAILED"

Aspect = Literal["correctness", "form"]


class HarnessReport(BaseModel):
    """One validation report plus the sampled coverage that produced it."""

    model_config = ConfigDict(extra="forbid", strict=True)

    report: ValidationReport
    checking_mode: Literal["property_based"] = "property_based"
    examples_checked: int = 0
    execution_calls: int = 0
    max_examples: int = MAX_VARIANTS
    max_execution_calls: int = 4 * MAX_VARIANTS
    timeout_seconds: float = PROPERTY_CHECK_TIMEOUT_SECONDS
    seed: int = 0
    whole_domain: bool = False
    declared_domain_size: int = 0

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
        options, duplicate_findings = _check_recipe_distractors(spec, params)
        option_findings = [*duplicate_findings, *_failed_option_findings(options)]

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
    status = _aggregate(
        [
            *[result.status for result in checks],
            *[option.result.status for option in options],
        ]
    )
    if status == "failed" and not findings:
        findings = ["the parameter combination failed validation"]
    return HarnessReport(
        report=ValidationReport(
            status=status,
            answer=display_sympy_value(declared),
            checks=checks,
            options=options,
            findings=findings,
        )
    )


def _failed_harness_report(
    message: str,
    *,
    declared_domain_size: int = 0,
    seed: int = 0,
) -> HarnessReport:
    """Return a failed report for an input that cannot be checked."""
    return HarnessReport(
        report=ValidationReport(status="failed", findings=[message]),
        declared_domain_size=declared_domain_size,
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
    """Check the declared domain. Any failing combination blocks the template."""
    if template.body.answer_recipe is None:
        return _failed_harness_report(
            "template body must declare an answer_recipe; an answer "
            "cannot be derived for it"
        )

    declared_size = declared_domain_size(template)
    parameters = _parameter_axes(template)
    if not _has_valid_combination(parameters):
        return _failed_harness_report(
            "template has no parameter combinations",
            declared_domain_size=declared_size,
            seed=seed,
        )

    boundary = _boundary_examples(template)
    if declared_size <= max_variants:
        # A small domain is enumerated completely, so the generation budget
        # does not need to leave room for generated examples.
        generation_budget = max_variants
    else:
        # Keep the whole run within the requested variant budget. At least one
        # generated example remains so the seed still changes the sample, and
        # the boundary examples fill the rest.
        generation_budget = min(max(1, max_variants - len(boundary)), max_variants)
        boundary = boundary[: max_variants - generation_budget]
    config = PropertyCheckSettings(
        max_examples=generation_budget,
        max_execution_calls=4 * max_variants,
        timeout_seconds=PROPERTY_CHECK_TIMEOUT_SECONDS,
        seed=seed,
    )
    run = PropertyCheckRun(config)
    first_failure: list[tuple[str, HarnessReport]] = []

    def check_case(
        combination: dict[str, Any], budget: PropertyCheckRun
    ) -> HarnessReport:
        # The declared domain may contain literals that are not exact numbers.
        # They are not members of the checkable domain, so reject the sample.
        assume(_is_valid_combination(combination))
        budget.reserve_execution()
        result = validate_item(template.body, params=combination, aspect=aspect)
        if result.report.status == "failed":
            if not first_failure:
                # Shrinking spends execution calls, so keep this report in case
                # the budget runs out before the property run finishes.
                first_failure.append((_variant_text(combination), result))
            raise ValidationFailure(
                "a parameter combination failed validation",
                code=_VARIANT_FAILED,
                context={
                    "variant": _variant_text(combination),
                    "harness_report": result.model_dump(mode="json"),
                },
            )
        return result

    try:
        reports = run.check(
            parameters,
            boundary,
            check_case,
            cover_small_domain=True,
        )
    except Unsatisfiable:
        return _failed_harness_report(
            "template has no parameter combinations",
            declared_domain_size=declared_size,
            seed=seed,
        )
    except ValidationFailure as exc:
        if exc.code == "PROPERTY_CHECK_BUDGET_EXCEEDED" and first_failure:
            variant, failing = first_failure[0]
            return _variant_failure_report(
                variant,
                failing,
                details=run.details(),
            )
        return _property_failure_report(exc)

    details = run.details()
    return HarnessReport(
        report=ValidationReport(
            status=_sampled_status(reports),
            answer=reports[0].report.answer if reports else "",
            checks=[item for report in reports for item in report.report.checks],
            options=[item for report in reports for item in report.report.options],
            findings=_variant_findings(reports),
        ),
        **details,
    )


def _parameter_axes(template: MathTemplateSpec) -> dict[str, list[Any]]:
    """Declared values per parameter, in declaration order.

    Exact literals become ``Fraction`` values. A literal that is not an exact
    number stays as its raw string so the checker can skip that combination
    instead of silently treating it as a member of the domain.
    """
    return {
        parameter.name: [_exact_value(value) for value in parameter.values]
        for parameter in template.parameters
    }


def _exact_value(value: str) -> Any:
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return value


def _is_valid_combination(combination: dict[str, Any]) -> bool:
    return all(isinstance(value, Fraction) for value in combination.values())


def _has_valid_combination(parameters: dict[str, list[Any]]) -> bool:
    """Whether every axis declares at least one exact value."""
    return all(
        any(isinstance(value, Fraction) for value in values)
        for values in parameters.values()
    )


def _boundary_examples(template: MathTemplateSpec) -> list[dict[str, Fraction]]:
    """A few axis boundaries, mirroring the code domain's boundary examples."""
    declared = _parameter_axes(template)
    axes = {
        name: [value for value in values if isinstance(value, Fraction)]
        for name, values in declared.items()
    }
    if not _has_valid_combination(axes):
        return []

    base = {name: values[0] for name, values in axes.items()}
    examples = [base, {name: values[-1] for name, values in axes.items()}]
    for parameter in template.parameters:
        values = axes[parameter.name]
        examples.append(base | {parameter.name: values[-1]})
        if Fraction(0) in values:
            examples.append(base | {parameter.name: Fraction(0)})

    unique: dict[tuple[tuple[str, str], ...], dict[str, Fraction]] = {}
    for example in examples:
        unique[_combination_key(example)] = example
    return list(unique.values())


def _combination_key(combination: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple((name, str(value)) for name, value in sorted(combination.items()))


def _variant_text(combination: dict[str, Any]) -> str:
    """Render one combination for a finding, using the question's notation."""
    return ", ".join(
        f"{name}={fraction_text(value) if isinstance(value, Fraction) else value}"
        for name, value in combination.items()
    )


def _property_failure_report(
    failure: ValidationFailure,
) -> HarnessReport:
    """Turn a property-check failure into a failed harness report."""
    checked = property_details(failure.context)
    if failure.code == "PROPERTY_CHECK_BUDGET_EXCEEDED":
        return HarnessReport(
            report=ValidationReport(
                status="failed",
                findings=[f"{failure} ({failure.code})"],
            ),
            **checked,
        )
    if failure.code != _VARIANT_FAILED:
        raise failure

    failing = HarnessReport.model_validate(failure.context["harness_report"])
    return _variant_failure_report(
        failure.context["variant"],
        failing,
        details=checked,
    )


def _variant_failure_report(
    variant: str,
    failing: HarnessReport,
    *,
    details: dict[str, Any],
) -> HarnessReport:
    """Report one failed variant, keeping its findings and coverage."""
    prefix = f"variant {variant}:"
    findings = [f"{prefix} {finding}" for finding in failing.report.findings]
    if not findings:
        findings = [f"{prefix} the variant failed validation"]
    return HarnessReport(
        report=ValidationReport(
            status="failed",
            answer=failing.report.answer,
            checks=failing.report.checks,
            options=failing.report.options,
            findings=findings,
        ),
        **details,
    )


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
