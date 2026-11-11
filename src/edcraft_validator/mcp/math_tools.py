"""Exact structure and answer checks plus advisory math assessments."""

from __future__ import annotations

import time
from fractions import Fraction
from functools import partial
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from edcraft_validator.application.authoring_contracts import DifficultyOutcome
from edcraft_validator.application.fidelity.engine import verify_text_fidelity
from edcraft_validator.domains.math.candidate_builder import template_sha256
from edcraft_validator.domains.math.fidelity import math_fidelity_plugin
from edcraft_validator.domains.math.ir.schema import MathItemSpec, MathTemplateSpec
from edcraft_validator.domains.math.linear_ir import (
    MAX_IR_VARIANTS,
    linear_template_ir,
)
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    parameter_combinations,
    template_fields,
)
from edcraft_validator.domains.math.math_types import (
    MATH_ANSWERS_TOOL,
    MATH_CHECKING_MODE,
    MATH_DIFFICULTY_TOOL,
    MATH_FIDELITY_TOOL,
    MATH_IR_TOOL_VERSION,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
    MATH_PARAMETER_NAMES,
    MATH_STRUCTURE_TOOL,
    MATH_TOOL_VERSION,
    MAX_DISTRACTORS,
    MIN_DISTRACTORS,
)
from edcraft_validator.domains.math.safe_linear import (
    evaluate_expression,
    format_fraction,
    validate_expression,
)
from edcraft_validator.domains.math.validation.harness import Witness
from edcraft_validator.domains.math.validation.isolation import (
    DEFAULT_VALIDATION_TIMEOUT_SECONDS,
    ValidationTimeout,
    ValidationWorkerError,
    run_isolated,
)
from edcraft_validator.llm.judge_configuration import (
    configured_judge_provider,
    load_judge_settings,
)
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding

CandidateArgument = Annotated[
    MathTemplateCandidate,
    Field(
        description=(
            "Complete linear-equation template candidate to check. The tool treats "
            "it as untrusted input and does not modify the supplied object."
        )
    ),
]


class MathSpecRequest(BaseModel):
    """One IR item, a finite template sweep, or a legacy linear candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathItemSpec | None = None
    template: MathTemplateSpec | None = None
    candidate: MathTemplateCandidate | None = None
    witnesses: list[Witness] = Field(default_factory=list, max_length=32)
    max_variants: int = Field(default=64, ge=1, le=512)
    check_distractors: bool = True
    timeout_seconds: float = Field(
        default=DEFAULT_VALIDATION_TIMEOUT_SECONDS, gt=0, le=60
    )

    @model_validator(mode="after")
    def require_one_spec(self) -> MathSpecRequest:
        supplied = sum(
            value is not None for value in (self.item, self.template, self.candidate)
        )
        if supplied != 1:
            raise ValueError("supply exactly one of item, template, or candidate")
        return self


class MathFidelityRequest(BaseModel):
    """Blind parse-back check for a prose math item."""

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathItemSpec
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    timeout_seconds: float = Field(default=60.0, gt=0, le=310)

    @model_validator(mode="after")
    def require_rendered_text(self) -> MathFidelityRequest:
        if self.text is None and not self.item.text.template.strip():
            raise ValueError("item text is empty")
        return self


class MathOptionsRequest(BaseModel):
    """MCQ option checks for one concrete item or a legacy linear candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathItemSpec | None = None
    candidate: MathTemplateCandidate | None = None
    timeout_seconds: float = Field(
        default=DEFAULT_VALIDATION_TIMEOUT_SECONDS, gt=0, le=60
    )

    @model_validator(mode="after")
    def require_one_spec(self) -> MathOptionsRequest:
        if (self.item is None) == (self.candidate is None):
            raise ValueError("supply exactly one of item or candidate")
        return self


class MathToolFailure(ValueError):
    """A validation failure with an actionable finding code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TEMPLATE_INVALID",
        field: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.context = context or {}


def register_math_tools(
    server: FastMCP,
    *,
    fidelity_provider_factory: JudgeProviderFactory | None = None,
    fidelity_timeout_seconds: float = 60.0,
) -> None:
    """Register the math-domain validation and advisory catalogue."""
    if fidelity_timeout_seconds <= 0:
        raise ValueError("fidelity timeout must be positive")
    selected_provider = fidelity_provider_factory
    if selected_provider is None:
        settings = load_judge_settings()
        selected_provider = partial(configured_judge_provider, settings)

    @server.tool(
        name=MATH_STRUCTURE_TOOL,
        version=MATH_TOOL_VERSION,
        tags={"domain:math"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Establish that a linear-equation template uses the supported "
            "a, b, c parameters, well-formed equation and question placeholders, "
            "bounded integer values, at least one distractor, and only the allowed "
            "arithmetic expression subset. The check is static and does not "
            "compute answers or establish that distractors are wrong."
        ),
    )
    async def math_verify_template_structure(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        return _run_tool(
            MATH_STRUCTURE_TOOL,
            lambda: verify_template_structure(candidate),
        )

    @server.tool(
        name=MATH_ANSWERS_TOOL,
        version=MATH_TOOL_VERSION,
        tags={"domain:math"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Exhaustively enumerate the bounded a, b, c parameter domain and "
            "compute exact rational answers for the answer recipe. Require every "
            "answer to be well-defined, every selected distractor to differ from "
            "the answer, and all selected distractors to be pairwise distinct for "
            "every declared combination. Returns the checked distractor recipes "
            "in details.selected_distractors. This is bounded-domain evidence, not "
            "proof for undeclared coefficient values; generated drafts still "
            "require manual review."
        ),
    )
    async def math_validate_answers_and_distractors(
        candidate: CandidateArgument,
        required_distractors: Annotated[
            int,
            Field(
                ge=MIN_DISTRACTORS,
                le=MAX_DISTRACTORS,
                description="Number of checked learner-facing distractors required.",
            ),
        ],
    ) -> ToolEvidence:
        return _run_tool(
            MATH_ANSWERS_TOOL,
            lambda: validate_answers_and_distractors(candidate, required_distractors),
        )

    @server.tool(
        name=MATH_DIFFICULTY_TOOL,
        version=MATH_TOOL_VERSION,
        tags={
            "domain:math",
            "quality:math",
            "stage:after-validation",
            "policy:advisory",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Provide a provisional heuristic difficulty assessment for a checked "
            "linear-equation template. Uses coefficient magnitude, sign variety, "
            "parameter-domain size, and distractor count. The estimate is advisory "
            "and uncalibrated; a mismatch never blocks a technically checked "
            "template or requests author revision. No model call is made."
        ),
    )
    async def math_assess_template_difficulty(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        return assess_template_difficulty(candidate)

    @server.tool(
        name=MATH_ITEM_SPEC_TOOL,
        version=MATH_IR_TOOL_VERSION,
        tags={"domain:math", "validation:ir"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Compile a typed math IR item (or sweep a finite parameter template) "
            "in a disposable process, derive the answer with exact SymPy "
            "arithmetic, compare any declared answer, and check every distractor. "
            "Returns passed, failed, or an inconclusive result that must be "
            "reviewed. The tool never executes model-authored code."
        ),
    )
    async def math_verify_item_spec(
        item: MathItemSpec | None = None,
        template: MathTemplateSpec | None = None,
        candidate: MathTemplateCandidate | None = None,
        witnesses: list[Witness] | None = None,
        max_variants: Annotated[int, Field(ge=1, le=512)] = 64,
        check_distractors: bool = True,
        timeout_seconds: Annotated[float, Field(gt=0, le=60)] = (
            DEFAULT_VALIDATION_TIMEOUT_SECONDS
        ),
    ) -> ToolEvidence:
        return verify_item_spec(
            MathSpecRequest(
                item=item,
                template=template,
                candidate=candidate,
                witnesses=witnesses or [],
                max_variants=max_variants,
                check_distractors=check_distractors,
                timeout_seconds=timeout_seconds,
            )
        )

    @server.tool(
        name=MATH_OPTIONS_TOOL,
        version=MATH_IR_TOOL_VERSION,
        tags={"domain:math", "validation:options"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Check MCQ options deterministically against the derived key: every "
            "distractor must be demonstrably wrong, no distractor may equal the "
            "key, and no two options may be equivalent. Each option carries a "
            "misconception tag. Inconclusive options block approval and route to "
            "review."
        ),
    )
    async def math_validate_options(
        item: MathItemSpec | None = None,
        candidate: MathTemplateCandidate | None = None,
        timeout_seconds: Annotated[float, Field(gt=0, le=60)] = (
            DEFAULT_VALIDATION_TIMEOUT_SECONDS
        ),
    ) -> ToolEvidence:
        return validate_options(
            MathOptionsRequest(
                item=item,
                candidate=candidate,
                timeout_seconds=timeout_seconds,
            )
        )

    @server.tool(
        name=MATH_FIDELITY_TOOL,
        version=MATH_IR_TOOL_VERSION,
        tags={"domain:math", "validation:fidelity"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        description=(
            "Run the independent NL-fidelity gate for a prose math item. Anchors "
            "are checked first; then a blind parse-back model reconstructs the "
            "problem without seeing the expected IR. A mismatch quarantines the "
            "item and judge failures are inconclusive, never approved. Symbolic "
            "templates skip the model call because the renderer is constrained."
        ),
    )
    async def math_verify_text_fidelity(
        item: MathItemSpec,
        text: Annotated[str | None, Field(min_length=1, max_length=4000)] = None,
        timeout_seconds: Annotated[float, Field(gt=0, le=310)] = 60.0,
    ) -> ToolEvidence:
        request = MathFidelityRequest(
            item=item,
            text=text,
            timeout_seconds=timeout_seconds,
        )
        return await verify_text_fidelity_tool(
            request,
            provider_factory=selected_provider,
            timeout_seconds=min(request.timeout_seconds, fidelity_timeout_seconds),
        )


async def verify_text_fidelity_tool(
    request: MathFidelityRequest,
    *,
    provider_factory: JudgeProviderFactory,
    timeout_seconds: float,
) -> ToolEvidence:
    started = time.perf_counter()
    try:
        report = await verify_text_fidelity(
            math_fidelity_plugin(),
            request.item,
            request.text or request.item.text.template,
            provider_factory=provider_factory,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - the tool boundary reports failures
        return ToolEvidence(
            tool=MATH_FIDELITY_TOOL,
            version=MATH_IR_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="FIDELITY_EXECUTION_ERROR",
                    message=f"fidelity check failed with {type(exc).__name__}",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    if report.status == "passed":
        status = "passed"
        findings = []
    else:
        status = "failed"
        code = (
            "FIDELITY_INCONCLUSIVE"
            if report.status == "inconclusive"
            else "FIDELITY_MISMATCH"
        )
        findings = [
            ToolFinding(code=code, message=reason)
            for reason in (report.verdict.reasons or ["fidelity check did not pass"])
        ]
    return ToolEvidence(
        tool=MATH_FIDELITY_TOOL,
        version=MATH_IR_TOOL_VERSION,
        status=status,
        findings=findings,
        details={
            **report.model_dump(mode="json"),
            "routes_to_review": report.status != "passed",
        },
        duration_ms=_elapsed_ms(started),
    )


def verify_item_spec(request: MathSpecRequest) -> ToolEvidence:
    operation = "validate_item"
    template = request.template
    if request.candidate is not None:
        template = linear_template_ir(request.candidate)
    if template is not None:
        operation = "validate_template"
    payload: dict[str, Any] = {
        "operation": operation,
        "witnesses": [item.model_dump(mode="json") for item in request.witnesses],
        "max_variants": min(request.max_variants, MAX_IR_VARIANTS),
        "check_distractors": request.check_distractors,
    }
    if template is not None:
        payload["template"] = template.model_dump(mode="json")
    else:
        payload["spec"] = request.item.model_dump(mode="json")  # type: ignore[union-attr]
    return _run_isolated(MATH_ITEM_SPEC_TOOL, payload, request.timeout_seconds)


def validate_options(request: MathOptionsRequest) -> ToolEvidence:
    if request.candidate is not None:
        template = linear_template_ir(request.candidate)
        if not template.body.distractors:
            return _no_options(MATH_OPTIONS_TOOL, "candidate.distractors")
        payload = {
            "operation": "validate_template",
            "template": template.model_dump(mode="json"),
            "max_variants": MAX_IR_VARIANTS,
            "check_distractors": True,
        }
    else:
        assert request.item is not None
        if not request.item.distractors:
            return _no_options(MATH_OPTIONS_TOOL, "item.distractors")
        payload = {
            "operation": "validate_item",
            "spec": request.item.model_dump(mode="json"),
            "check_distractors": True,
        }
    return _run_isolated(MATH_OPTIONS_TOOL, payload, request.timeout_seconds)


def _no_options(name: str, field: str) -> ToolEvidence:
    return ToolEvidence(
        tool=name,
        version=MATH_IR_TOOL_VERSION,
        status="failed",
        findings=[
            ToolFinding(
                code="NO_OPTIONS",
                message="the item declares no distractor options",
                field=field,
            )
        ],
    )


def _run_isolated(
    name: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> ToolEvidence:
    started = time.perf_counter()
    try:
        response = run_isolated(payload, timeout_seconds=timeout_seconds)
    except ValidationTimeout:
        return ToolEvidence(
            tool=name,
            version=MATH_IR_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="VALIDATION_TIMEOUT",
                    message=f"validation exceeded {timeout_seconds:g}s",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    except ValidationWorkerError as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_IR_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="VALIDATION_WORKER_ERROR",
                    message=str(exc),
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    report = response.get("report")
    if not isinstance(report, dict):
        return ToolEvidence(
            tool=name,
            version=MATH_IR_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="VALIDATION_RESPONSE_MALFORMED",
                    message="validation worker did not return a report",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    return _harness_evidence(name, report, started)


def _harness_evidence(
    name: str,
    harness: dict[str, Any],
    started: float,
) -> ToolEvidence:
    report = harness.get("report")
    if not isinstance(report, dict):
        return ToolEvidence(
            tool=name,
            version=MATH_IR_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="VALIDATION_RESPONSE_MALFORMED",
                    message="validation report is missing",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    ir_status = str(report.get("status", "inconclusive"))
    findings = [str(item) for item in report.get("findings", []) if item]
    options = report.get("options", [])
    if name == MATH_OPTIONS_TOOL:
        failed_options = [
            option
            for option in options
            if option.get("result", {}).get("status") != "passed"
        ]
        if failed_options:
            ir_status = (
                "inconclusive"
                if all(
                    option.get("result", {}).get("status") == "inconclusive"
                    for option in failed_options
                )
                else "failed"
            )
            findings = [
                f"option {option.get('index')}: "
                f"{option.get('result', {}).get('reason', '')}"
                for option in failed_options
            ]
    if ir_status == "passed":
        status = "passed"
    else:
        status = "failed"
        if not findings:
            findings = ["validation did not pass"]
    codes = {
        "failed": "IR_VALIDATION_FAILED",
        "inconclusive": "IR_VALIDATION_INCONCLUSIVE",
    }
    if name == MATH_OPTIONS_TOOL:
        codes = {
            "failed": "OPTION_CHECK_FAILED",
            "inconclusive": "OPTION_CHECK_INCONCLUSIVE",
        }
    tool_findings = [
        ToolFinding(code=codes.get(ir_status, "IR_VALIDATION_FAILED"), message=message)
        for message in findings[:20]
    ]
    return ToolEvidence(
        tool=name,
        version=MATH_IR_TOOL_VERSION,
        status=status,
        findings=tool_findings,
        details={
            "ir_status": ir_status,
            "routes_to_review": ir_status != "passed",
            "answer": report.get("answer", ""),
            "findings": findings,
            "witnesses": harness.get("witnesses", []),
            "variants_checked": harness.get("variants_checked", 0),
            "primitives": report.get("primitives", []),
            "options": options,
        },
        duration_ms=_elapsed_ms(started),
    )


def _run_tool(name: str, operation) -> ToolEvidence:
    started = time.perf_counter()
    try:
        details = operation()
    except MathToolFailure as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_TOOL_VERSION,
            status="failed",
            findings=[ToolFinding(code=exc.code, message=str(exc), field=exc.field)],
            details=exc.context,
            duration_ms=_elapsed_ms(started),
        )
    except ValidationError as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_TOOL_VERSION,
            status="failed",
            findings=[
                ToolFinding(
                    code="TEMPLATE_INVALID",
                    message=f"Candidate does not match the math template schema: {exc}",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="TOOL_EXECUTION_ERROR",
                    message=f"Validation tool failed with {type(exc).__name__}",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    return ToolEvidence(
        tool=name,
        version=MATH_TOOL_VERSION,
        status="passed",
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def verify_template_structure(
    candidate: MathTemplateCandidate,
) -> dict[str, Any]:
    """Check placeholders, bounds, and the allowlisted expression subset."""
    candidate = _revalidate(candidate)
    try:
        validate_expression(candidate.answer_expression)
    except ValueError as exc:
        raise MathToolFailure(
            f"Answer expression is unsupported: {exc}",
            code="EXPRESSION_UNSUPPORTED",
            field="answer_expression",
        ) from exc
    for index, recipe in enumerate(candidate.distractors):
        try:
            validate_expression(recipe.expression)
        except ValueError as exc:
            raise MathToolFailure(
                f"Distractor expression is unsupported: {exc}",
                code="EXPRESSION_UNSUPPORTED",
                field=f"distractors.{index}.expression",
            ) from exc
        try:
            unknown = template_fields(recipe.reason_template) - set(
                MATH_PARAMETER_NAMES
            )
        except ValueError as exc:
            raise MathToolFailure(
                f"Distractor reason template is invalid: {exc}",
                code="REASON_TEMPLATE_INVALID",
                field=f"distractors.{index}.reason_template",
            ) from exc
        if unknown:
            raise MathToolFailure(
                "Distractor reason uses unsupported placeholders: "
                + ", ".join(sorted(unknown)),
                code="REASON_PLACEHOLDER_UNSUPPORTED",
                field=f"distractors.{index}.reason_template",
            )
    combinations = _parameter_combinations(candidate)
    return {
        "parameters": len(candidate.parameters),
        "combinations": len(combinations),
        "distractors": len(candidate.distractors),
        "expressions_checked": 1 + len(candidate.distractors),
    }


def validate_answers_and_distractors(
    candidate: MathTemplateCandidate, required_distractors: int
) -> dict[str, Any]:
    """Check exact answers and distractors over the complete bounded domain."""
    candidate = _revalidate(candidate)
    if not MIN_DISTRACTORS <= required_distractors <= MAX_DISTRACTORS:
        raise MathToolFailure(
            "Required distractor count is outside the supported range",
            code="DISTRACTOR_COUNT_INVALID",
            field="required_distractors",
        )
    if len(candidate.distractors) < required_distractors:
        raise MathToolFailure(
            "The template supplies fewer distractor recipes than required",
            code="INSUFFICIENT_DISTRACTORS",
            field="distractors",
            context={
                "available": len(candidate.distractors),
                "required": required_distractors,
            },
        )
    combinations = _parameter_combinations(candidate)
    selected = candidate.distractors[:required_distractors]
    for values in combinations:
        # The candidate schema fixes the equation shape to a*x + b = c and
        # rejects a == 0, so solve it exactly instead of trusting the recipe.
        canonical_answer = Fraction(values["c"] - values["b"], values["a"])
        try:
            answer = evaluate_expression(candidate.answer_expression, values)
        except ValueError as exc:
            raise MathToolFailure(
                f"Answer recipe is not well-defined: {exc}",
                code="ANSWER_UNDEFINED",
                field="answer_expression",
                context={"failing_parameters": values},
            ) from exc
        if answer != canonical_answer:
            raise MathToolFailure(
                "Answer recipe does not solve the equation for this combination",
                code="ANSWER_INCORRECT",
                field="answer_expression",
                context={
                    "failing_parameters": values,
                    "expected": format_fraction(canonical_answer),
                    "actual": format_fraction(answer),
                },
            )
        seen: set[Any] = {canonical_answer}
        for index, recipe in enumerate(selected):
            try:
                distractor = evaluate_expression(recipe.expression, values)
            except ValueError as exc:
                raise MathToolFailure(
                    f"Distractor recipe is not well-defined: {exc}",
                    code="DISTRACTOR_UNDEFINED",
                    field=f"distractors.{index}.expression",
                    context={"failing_parameters": values},
                ) from exc
            if distractor == canonical_answer:
                raise MathToolFailure(
                    "A distractor coincides with the answer for a declared "
                    "parameter combination",
                    code="DISTRACTOR_MATCHES_ANSWER",
                    field=f"distractors.{index}.expression",
                    context={
                        "failing_parameters": values,
                        "distractor_index": index,
                    },
                )
            if distractor in seen:
                raise MathToolFailure(
                    "Two selected distractors coincide for a declared parameter "
                    "combination",
                    code="DISTRACTOR_COLLISION",
                    field=f"distractors.{index}.expression",
                    context={
                        "failing_parameters": values,
                        "distractor_index": index,
                    },
                )
            seen.add(distractor)
    return {
        "checking_mode": MATH_CHECKING_MODE,
        "combinations_checked": len(combinations),
        "max_combinations": len(combinations),
        "seed": 0,
        "selected_distractors": [recipe.model_dump(mode="json") for recipe in selected],
    }


def assess_template_difficulty(
    candidate: MathTemplateCandidate,
) -> ToolEvidence:
    """Return a deterministic provisional difficulty estimate."""
    started = time.perf_counter()
    candidate = _revalidate(candidate)
    estimate = _estimate_difficulty(candidate)
    matches = estimate == candidate.difficulty
    outcome = DifficultyOutcome(
        # This is a deterministic policy rule, not model reasoning and not a
        # calibrated confidence. Reporting either would misstate the evidence.
        assessment_path="decision",
        requested_difficulty=candidate.difficulty,
        estimated_difficulty=estimate,
        decision="matches" if matches else "advisory_mismatch",
        status="passed" if matches else "failed",
        reason=(
            "Provisional deterministic heuristic from coefficient magnitude, sign "
            "variety, parameter-domain size, and distractor count; not calibrated."
        ),
    )
    findings = (
        []
        if matches
        else [
            ToolFinding(
                code="DIFFICULTY_MISMATCH",
                message=(
                    f"Heuristic estimate is {estimate}; requested "
                    f"{candidate.difficulty}. Advisory only."
                ),
                field="difficulty",
            )
        ]
    )
    details = {
        "advisory": True,
        "provisional": True,
        "calibrated": False,
        "template_sha256": template_sha256(candidate),
        "requested_difficulty": candidate.difficulty,
        "difficulty_outcome": outcome.model_dump(mode="json"),
        **outcome.model_dump(
            mode="json",
            include={
                "assessment_path",
                "requested_difficulty",
                "estimated_difficulty",
                "confidence",
                "confidence_source",
                "decision",
            },
        ),
    }
    return ToolEvidence(
        tool=MATH_DIFFICULTY_TOOL,
        version=MATH_TOOL_VERSION,
        status=outcome.status,
        findings=findings,
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def _revalidate(candidate: MathTemplateCandidate) -> MathTemplateCandidate:
    try:
        return MathTemplateCandidate.model_validate(candidate.model_dump())
    except ValidationError as exc:
        raise MathToolFailure(
            f"Candidate does not match the math template schema: {exc}",
            code="TEMPLATE_INVALID",
        ) from exc


def _parameter_combinations(
    candidate: MathTemplateCandidate,
) -> list[dict[str, int]]:
    return parameter_combinations(candidate.parameters)


def _estimate_difficulty(candidate: MathTemplateCandidate) -> str:
    parameters = {
        parameter.name: parameter.values for parameter in candidate.parameters
    }
    score = 0
    if max(abs(value) for value in parameters["a"]) > 1:
        score += 1
    if any(value < 0 for values in parameters.values() for value in values):
        score += 1
    if max(abs(value) for values in parameters.values() for value in values) >= 10:
        score += 1
    combination_count = len(_parameter_combinations(candidate))
    if combination_count >= 60:
        score += 1
    if len(candidate.distractors) >= 4:
        score += 1
    if score <= 1:
        return "easy"
    if score <= 3:
        return "medium"
    return "hard"


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
