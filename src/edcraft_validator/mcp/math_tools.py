"""Math-domain validation and advisory tools for the authoring flow.

The tools treat a model proposal as an untrusted candidate and run exact,
fidelity and advisory checks through MCP before the application finalises it.
"""

from __future__ import annotations

import time
from functools import partial
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from edcraft_validator.application.fidelity.contracts import FidelityReport
from edcraft_validator.application.fidelity.engine import verify_text_fidelity
from edcraft_validator.domains.math.difficulty import assess_template_difficulty
from edcraft_validator.domains.math.fidelity import math_fidelity_plugin
from edcraft_validator.domains.math.ir.schema import MathItemSpec, MathTemplateSpec
from edcraft_validator.domains.math.math_schemas import MathTemplateCandidate
from edcraft_validator.domains.math.math_types import (
    MATH_DIFFICULTY_TOOL,
    MATH_FIDELITY_TOOL,
    MATH_FORM_TOOL,
    MATH_IR_TOOL_VERSION,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
    MATH_TOOL_VERSION,
    MAX_IR_VARIANTS,
)
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
from edcraft_validator.validation.property_checks import PropertyCheckSettings

_MAX_EXPORTED_ITEMS = 128

CandidateArgument = Annotated[
    MathTemplateCandidate,
    Field(
        description=(
            "Complete math template candidate to check. The tool treats it as "
            "untrusted input and does not modify the supplied object."
        )
    ),
]


class MathSpecRequest(BaseModel):
    """One IR item, a sampled parameter template, or a math template candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathItemSpec | None = None
    template: MathTemplateSpec | None = None
    candidate: MathTemplateCandidate | None = None
    max_variants: int = Field(default=MAX_IR_VARIANTS, ge=1, le=MAX_IR_VARIANTS)
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
    """MCQ option checks for one concrete item, a sampled template, or a candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    item: MathItemSpec | None = None
    template: MathTemplateSpec | None = None
    candidate: MathTemplateCandidate | None = None
    timeout_seconds: float = Field(
        default=DEFAULT_VALIDATION_TIMEOUT_SECONDS, gt=0, le=60
    )

    @model_validator(mode="after")
    def require_one_subject(self) -> MathOptionsRequest:
        supplied = sum(
            value is not None for value in (self.item, self.template, self.candidate)
        )
        if supplied != 1:
            raise ValueError("supply exactly one of item, template, or candidate")
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
        name=MATH_DIFFICULTY_TOOL,
        version=MATH_TOOL_VERSION,
        tags={
            "domain:math",
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
            "math template. Uses parameter-count, magnitude, sign variety, "
            "parameter-domain size, and distractor count. The estimate is advisory "
            "and uncalibrated; a mismatch never blocks a technically checked "
            "template or requests author revision. No model call is made."
        ),
    )
    async def math_assess_template_difficulty(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        return assess_template_difficulty(_revalidate(candidate))

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
            "Compile a typed math IR item (or sample a parameter template's "
            "declared domain) in a disposable process: the deterministic engine "
            "grades the authored answer recipe and every distractor. It decides "
            "correctness only; answer form is a separate check. Returns passed, "
            "failed, or an inconclusive result that must be reviewed. The tool "
            "never executes model-authored code."
        ),
    )
    async def math_verify_item_spec(
        item: MathItemSpec | None = None,
        template: MathTemplateSpec | None = None,
        candidate: MathTemplateCandidate | None = None,
        max_variants: Annotated[int, Field(ge=1, le=MAX_IR_VARIANTS)] = (
            MAX_IR_VARIANTS
        ),
        timeout_seconds: Annotated[float, Field(gt=0, le=60)] = (
            DEFAULT_VALIDATION_TIMEOUT_SECONDS
        ),
    ) -> ToolEvidence:
        return verify_item_spec(
            MathSpecRequest(
                item=item,
                template=template,
                candidate=candidate,
                max_variants=max_variants,
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
            "Check MCQ options deterministically: the engine must grade every "
            "distractor as incorrect while grading the answer recipe as correct, "
            "and no two options may be the same value. Each option carries a "
            "misconception tag. Any refusal fails the option and blocks approval."
        ),
    )
    async def math_validate_options(
        item: MathItemSpec | None = None,
        template: MathTemplateSpec | None = None,
        candidate: MathTemplateCandidate | None = None,
        timeout_seconds: Annotated[float, Field(gt=0, le=60)] = (
            DEFAULT_VALIDATION_TIMEOUT_SECONDS
        ),
    ) -> ToolEvidence:
        return validate_options(
            MathOptionsRequest(
                item=item,
                template=template,
                candidate=candidate,
                timeout_seconds=timeout_seconds,
            )
        )

    @server.tool(
        name=MATH_FORM_TOOL,
        version=MATH_IR_TOOL_VERSION,
        tags={"domain:math", "validation:form"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Check that the authored answer has the shape its goal demands, for "
            "example a fully expanded polynomial for expand or a product of "
            "irreducible factors for factor. Factor and expand goals apply the "
            "same rule to every distractor. The check does not decide "
            "correctness. It is required for factor and expand goals and "
            "optional for every other goal."
        ),
    )
    async def math_verify_answer_form(
        item: MathItemSpec | None = None,
        template: MathTemplateSpec | None = None,
        candidate: MathTemplateCandidate | None = None,
        max_variants: Annotated[int, Field(ge=1, le=MAX_IR_VARIANTS)] = (
            MAX_IR_VARIANTS
        ),
        timeout_seconds: Annotated[float, Field(gt=0, le=60)] = (
            DEFAULT_VALIDATION_TIMEOUT_SECONDS
        ),
    ) -> ToolEvidence:
        return verify_answer_form(
            MathSpecRequest(
                item=item,
                template=template,
                candidate=candidate,
                max_variants=max_variants,
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
        return _fidelity_error(exc, started)

    status, findings = _fidelity_outcome(report)
    return _fidelity_evidence(report, status, findings, started)


def _fidelity_error(exc: Exception, started: float) -> ToolEvidence:
    """Report an execution failure without leaking its message."""
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


def _fidelity_outcome(
    report: FidelityReport,
) -> tuple[Literal["passed", "failed"], list[ToolFinding]]:
    """Map a fidelity verdict onto the tool's status and findings."""
    if report.status == "passed":
        return "passed", []

    code = (
        "FIDELITY_INCONCLUSIVE"
        if report.status == "inconclusive"
        else "FIDELITY_MISMATCH"
    )
    reasons = report.verdict.reasons or ["fidelity check did not pass"]
    return "failed", [ToolFinding(code=code, message=reason) for reason in reasons]


def _fidelity_evidence(
    report: FidelityReport,
    status: Literal["passed", "failed"],
    findings: list[ToolFinding],
    started: float,
) -> ToolEvidence:
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
    return _verify_spec(MATH_ITEM_SPEC_TOOL, request, aspect="correctness")


def verify_answer_form(request: MathSpecRequest) -> ToolEvidence:
    return _verify_spec(MATH_FORM_TOOL, request, aspect="form")


def _verify_spec(
    name: str, request: MathSpecRequest, *, aspect: Literal["correctness", "form"]
) -> ToolEvidence:
    operation = "validate_item"
    template = request.template

    if request.candidate is not None:
        template = request.candidate.item
    if template is not None:
        operation = "validate_template"

    payload: dict[str, Any] = {
        "operation": operation,
        "aspect": aspect,
        "max_variants": min(request.max_variants, MAX_IR_VARIANTS),
    }
    if template is not None:
        payload["template"] = template.model_dump(mode="json")
    else:
        item = request.item
        if item is None:
            return _missing_subject(name, "item or template")
        payload["spec"] = item.model_dump(mode="json")

    return _run_isolated(name, payload, request.timeout_seconds)


def validate_options(request: MathOptionsRequest) -> ToolEvidence:
    template = request.template
    if request.candidate is not None:
        template = request.candidate.item

    if template is not None:
        if not template.body.distractors:
            return _no_options(MATH_OPTIONS_TOOL, "template.body.distractors")
        payload = {
            "operation": "validate_template",
            "template": template.model_dump(mode="json"),
            "max_variants": MAX_IR_VARIANTS,
        }
    else:
        item = request.item
        if item is None:
            return _missing_subject(MATH_OPTIONS_TOOL, "item, template, or candidate")
        if not item.distractors:
            return _no_options(MATH_OPTIONS_TOOL, "item.distractors")
        payload = {
            "operation": "validate_item",
            "spec": item.model_dump(mode="json"),
        }

    return _run_isolated(MATH_OPTIONS_TOOL, payload, request.timeout_seconds)


def _missing_subject(name: str, expected: str) -> ToolEvidence:
    return ToolEvidence(
        tool=name,
        version=MATH_IR_TOOL_VERSION,
        status="error",
        findings=[
            ToolFinding(
                code="NO_SUBJECT",
                message=f"validation requires {expected}",
            )
        ],
    )


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
        return _validation_error(
            name,
            "VALIDATION_TIMEOUT",
            f"validation exceeded {timeout_seconds:g}s",
            started,
        )
    except ValidationWorkerError as exc:
        return _validation_error(
            name,
            "VALIDATION_WORKER_ERROR",
            str(exc),
            started,
        )

    report = response.get("report")
    if not isinstance(report, dict):
        return _validation_error(
            name,
            "VALIDATION_RESPONSE_MALFORMED",
            "validation worker did not return a report",
            started,
        )
    return _harness_evidence(name, report, started)


def _validation_error(
    name: str,
    code: str,
    message: str,
    started: float,
) -> ToolEvidence:
    """Build an error result for a failed isolated run."""
    return ToolEvidence(
        tool=name,
        version=MATH_IR_TOOL_VERSION,
        status="error",
        findings=[ToolFinding(code=code, message=message)],
        duration_ms=_elapsed_ms(started),
    )


def _harness_evidence(
    name: str,
    harness: dict[str, Any],
    started: float,
) -> ToolEvidence:
    report = harness.get("report")
    if not isinstance(report, dict):
        return _validation_error(
            name,
            "VALIDATION_RESPONSE_MALFORMED",
            "validation report is missing",
            started,
        )

    ir_status, findings = _harness_status(name, report)
    if ir_status == "passed":
        status: Literal["passed", "failed"] = "passed"
    else:
        status = "failed"
        if not findings:
            findings = ["validation did not pass"]

    codes = _finding_codes(name)
    tool_findings = [
        ToolFinding(code=codes.get(ir_status, "IR_VALIDATION_FAILED"), message=message)
        for message in findings[:20]
    ]

    return ToolEvidence(
        tool=name,
        version=MATH_IR_TOOL_VERSION,
        status=status,
        findings=tool_findings,
        details=_harness_details(harness, report, ir_status, findings),
        duration_ms=_elapsed_ms(started),
    )


def _harness_status(name: str, report: dict[str, Any]) -> tuple[str, list[str]]:
    """Normalise the worker's status and collect every finding."""
    raw_status = report.get("status")
    findings = [str(item) for item in report.get("findings", []) if item]
    if raw_status not in {"passed", "failed", "inconclusive"}:
        ir_status = "inconclusive"
        findings = [
            f"validation worker returned unknown status {raw_status!r}",
            *findings,
        ]
    else:
        ir_status = str(raw_status)

    if name == MATH_OPTIONS_TOOL:
        failed_options = _failed_option_findings(report.get("options", []))
        if failed_options:
            ir_status = "failed"
            findings = [*findings, *failed_options]

    return ir_status, findings


def _failed_option_findings(options: list[dict[str, Any]]) -> list[str]:
    return [
        f"option {option.get('index')}: {option.get('result', {}).get('reason', '')}"
        for option in options
        if option.get("result", {}).get("status") != "passed"
    ]


def _finding_codes(name: str) -> dict[str, str]:
    """Choose the finding codes that suit the tool."""
    if name == MATH_OPTIONS_TOOL:
        return {
            "failed": "OPTION_CHECK_FAILED",
            "inconclusive": "OPTION_CHECK_INCONCLUSIVE",
        }
    return {
        "failed": "IR_VALIDATION_FAILED",
        "inconclusive": "IR_VALIDATION_INCONCLUSIVE",
    }


def _harness_details(
    harness: dict[str, Any],
    report: dict[str, Any],
    ir_status: str,
    findings: list[str],
) -> dict[str, Any]:
    """Export the sampled coverage and any truncated lists."""
    checks = report.get("checks", [])
    options = report.get("options", [])
    return {
        "ir_status": ir_status,
        "routes_to_review": ir_status != "passed",
        "answer": report.get("answer", ""),
        "findings": findings,
        "checking_mode": harness.get("checking_mode", "property_based"),
        "examples_checked": harness.get("examples_checked", 0),
        "execution_calls": harness.get("execution_calls", 0),
        "max_examples": harness.get("max_examples", PropertyCheckSettings.max_examples),
        "max_execution_calls": harness.get(
            "max_execution_calls", PropertyCheckSettings.max_execution_calls
        ),
        "timeout_seconds": harness.get(
            "timeout_seconds", PropertyCheckSettings.timeout_seconds
        ),
        "seed": harness.get("seed", 0),
        "whole_domain": harness.get("whole_domain", False),
        "declared_domain_size": harness.get("declared_domain_size", 0),
        "checks": checks[:_MAX_EXPORTED_ITEMS],
        "checks_truncated": len(checks) > _MAX_EXPORTED_ITEMS,
        "options": options[:_MAX_EXPORTED_ITEMS],
        "options_truncated": len(options) > _MAX_EXPORTED_ITEMS,
    }


def _revalidate(candidate: MathTemplateCandidate) -> MathTemplateCandidate:
    try:
        return MathTemplateCandidate.model_validate(candidate.model_dump())
    except ValidationError as exc:
        raise MathToolFailure(
            f"Candidate does not match the math template schema: {exc}",
            code="TEMPLATE_INVALID",
        ) from exc


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
