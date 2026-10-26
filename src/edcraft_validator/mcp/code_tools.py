"""Code checking tools, implementations, deadlines, and evidence."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
)
from edcraft_validator.domains.code.code_types import CodeFeature
from edcraft_validator.domains.code.features import extract_code_features
from edcraft_validator.mcp.code_checks.answer_checks import (
    check_canonical_answers,
    check_expressions,
    check_proposed_answers,
)
from edcraft_validator.mcp.code_checks.distractor_checks import (
    check_distractors,
    check_proposed_distractor_selection,
)
from edcraft_validator.mcp.code_checks.execution_check import ExecutionCheck
from edcraft_validator.mcp.code_checks.property_checks import (
    PropertyCheckRun,
    PropertyCheckSettings,
    boundary_examples,
)
from edcraft_validator.mcp.code_checks.structure_checks import (
    check_rendering,
    check_structure,
)
from edcraft_validator.mcp.code_checks.validation_context import (
    CodeValidationContext,
    DistractorCandidate,
)
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.validation_contracts import ValidationFailure
from edcraft_validator.value_comparison import equivalent, same_value_shape

CODE_TOOL_VERSION = "2.0.0"
STATIC_TOOL_TIMEOUT_SECONDS = 5.0


_EXECUTION_ERROR_CODES = {
    "CHECK_TIMEOUT",
    "EXECUTION_TIMEOUT",
    "EXECUTOR_PROTOCOL_ERROR",
    "INVALID_TOOL_OUTPUT",
    "RESOURCE_LIMIT_EXCEEDED",
    "TOOL_FAILURE",
    "TRACE_LIMIT_EXCEEDED",
    "PROPERTY_CHECK_BUDGET_EXCEEDED",
}


CandidateArgument = Annotated[
    CodeTemplateCandidate,
    Field(
        description=(
            "Complete code-template candidate to check. The tool treats it as "
            "untrusted input and does not modify the supplied object."
        )
    ),
]


def register_code_validation_tools(
    server: FastMCP,
    *,
    execution_tool: PythonExecutionTool,
    timeout_seconds: float,
    property_settings: PropertyCheckSettings | None = None,
) -> None:
    """Register the authoritative code-validation catalogue on ``server``."""
    property_settings = property_settings or PropertyCheckSettings()
    execution_timeout = property_settings.timeout_seconds + 2

    @server.tool(
        name="code_verify_template_structure",
        version=CODE_TOOL_VERSION,
        tags={"domain:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Select this tool to establish that a Python template uses the supported "
            "safe subset, declares a matching entry function and finite parameter "
            "domain, contains valid answer and distractor expressions, and renders "
            "for boundary examples. It performs static and expression checks only; "
            "it does not execute the program or establish that answers are correct."
        ),
    )
    async def code_verify_template_structure(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        return await _run_tool(
            "code_verify_template_structure",
            lambda: verify_template_structure(candidate),
            timeout_seconds=STATIC_TOOL_TIMEOUT_SECONDS,
        )

    @server.tool(
        name="code_validate_answers_and_distractors",
        version=CODE_TOOL_VERSION,
        tags={"domain:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Check answer and distractor recipes with bounded property-based "
            "sampling using Hypothesis, explicit boundary examples and shrunk "
            "counterexamples. Execute sampled inputs in isolated workers with a "
            f"{timeout_seconds:g}-second per-case timeout. Compare the answer "
            "recipe with execution and select a fixed set of proposed distractors "
            "that passes every checked sample. Known failures require revision; "
            "there are no fallback recipes or excluded-input tables. This is "
            "sampled evidence, not exhaustive verification. Unseen generated "
            "questions remain drafts for manual review. Execution, trace and "
            "sampling-budget limits return explicit error evidence. Only the "
            "supported Python subset is executed."
        ),
    )
    async def code_validate_answers_and_distractors(
        candidate: CandidateArgument,
        required_distractors: Annotated[
            int,
            Field(
                ge=2,
                le=3,
                description="Number of valid learner-facing distractors required.",
            ),
        ],
    ) -> ToolEvidence:
        return await _run_tool(
            "code_validate_answers_and_distractors",
            lambda: validate_answers_and_distractors(
                candidate,
                required_distractors,
                execution_tool=execution_tool,
                timeout_seconds=timeout_seconds,
                property_settings=property_settings,
            ),
            timeout_seconds=execution_timeout,
        )

    @server.tool(
        name="code_require_features",
        version=CODE_TOOL_VERSION,
        tags={"domain:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Select this tool when the authoring request requires concrete Python "
            "features such as a loop, conditional, helper function, or list operation. "
            "Require only features explicitly requested by the author; arithmetic "
            "alone does not require a loop or conditional. Correct mistaken feature "
            "arguments instead of adding unrelated code to satisfy them. "
            "helper_function means a separate helper called from the entry function. "
            "list_aggregate means calls to sum, min, max, all, or any, not manual "
            "accumulation in a loop. "
            "It checks the supported program structure and reports features reachable "
            "from the entry function. It establishes syntactic presence, not that the "
            "feature is pedagogically central or that the requested difficulty matches."
        ),
    )
    async def code_require_features(
        candidate: CandidateArgument,
        required: Annotated[
            list[CodeFeature],
            Field(
                min_length=1,
                description=(
                    "Features explicitly requested by the author that must occur "
                    "in reachable learner code. Follow the feature definitions "
                    "in this tool's description; do not invent extra requirements."
                ),
            ),
        ],
    ) -> ToolEvidence:
        return await _run_tool(
            "code_require_features",
            lambda: require_features(candidate, required),
            timeout_seconds=STATIC_TOOL_TIMEOUT_SECONDS,
        )


async def _run_tool(
    name: str,
    operation: Callable[[], dict[str, Any]],
    *,
    timeout_seconds: float,
) -> ToolEvidence:
    """Bound the MCP response deadline and discard late synchronous results.

    Thread cancellation cannot terminate synchronous work. Executable code retains
    the worker's process limits; deployment supplies the outer job resource limit.
    """
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            details = await asyncio.to_thread(operation)
    except ValidationFailure as exc:
        status = "error" if exc.code in _EXECUTION_ERROR_CODES else "failed"
        return ToolEvidence(
            tool=name,
            version=CODE_TOOL_VERSION,
            status=status,
            findings=[
                ToolFinding(
                    code=exc.code,
                    message=str(exc),
                    field=exc.field,
                )
            ],
            details=copy.deepcopy(exc.context),
            duration_ms=_elapsed_ms(started),
        )
    except TimeoutError:
        return _unexpected_error(
            name,
            started,
            code="CHECK_TIMEOUT",
            message="Validation tool exceeded its execution timeout",
        )
    except Exception as exc:
        return _unexpected_error(
            name,
            started,
            code="TOOL_EXECUTION_ERROR",
            message=f"Validation tool failed with {type(exc).__name__}",
        )
    return ToolEvidence(
        tool=name,
        version=CODE_TOOL_VERSION,
        status="passed",
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def _unexpected_error(
    name: str,
    started: float,
    *,
    code: str,
    message: str,
) -> ToolEvidence:
    return ToolEvidence(
        tool=name,
        version=CODE_TOOL_VERSION,
        status="error",
        findings=[ToolFinding(code=code, message=message)],
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def verify_template_structure(candidate: CodeTemplateCandidate) -> dict[str, Any]:
    context = CodeValidationContext(candidate)
    context.inputs_cases = boundary_examples(candidate)
    check_structure(context)
    check_expressions(context)
    check_proposed_answers(context)
    check_rendering(context)
    return {
        **context.case_details,
        "features": sorted(
            extract_code_features(
                context.template.code, context.template.entry_function
            )
        ),
    }


def validate_answers_and_distractors(
    candidate: CodeTemplateCandidate,
    required_distractors: int,
    *,
    execution_tool: PythonExecutionTool,
    timeout_seconds: float,
    property_settings: PropertyCheckSettings | None = None,
) -> dict[str, Any]:
    # Revalidate mutable Python caller objects as well as MCP boundary inputs.
    candidate = CodeTemplateCandidate.model_validate(candidate.model_dump())
    context = CodeValidationContext(candidate, num_distractors=required_distractors)
    check_structure(context)
    check_expressions(context)
    config = property_settings or PropertyCheckSettings()
    run = PropertyCheckRun(config)
    baseline_inputs = boundary_examples(candidate)[0]
    baseline = context.proposed_answer.evaluate(baseline_inputs)

    def check_case(inputs, budget):
        single = CodeValidationContext(candidate, num_distractors=required_distractors)
        single.inputs_cases = [inputs]
        single.eligible_indices = [0]
        single.proposed_answer = context.proposed_answer
        single.candidates = [
            DistractorCandidate(
                index=c.index, expression=c.expression, rejection=c.rejection
            )
            for c in context.candidates
        ]
        check_rendering(single)
        if inputs == baseline_inputs:
            single.proposed_answers = [baseline]
        else:
            check_proposed_answers(single)
        budget.reserve_execution()
        ExecutionCheck(
            execution_tool, min(timeout_seconds, budget.remaining_seconds)
        ).run(single)
        check_canonical_answers(single)
        proposed, actual = single.proposed_answers[0], single.canonical_answers[0]
        if not equivalent(proposed, actual):
            raise ValidationFailure(
                "The answer recipe disagrees with sampled execution",
                code="PROPOSED_ANSWER_MISMATCH",
                field="answer_expression",
                context={
                    "failing_inputs": copy.deepcopy(inputs),
                    "proposed": proposed,
                    "actual": actual,
                },
            )
        if not same_value_shape(actual, baseline):
            raise ValidationFailure(
                "Answer type changes across sampled cases",
                code="ANSWER_TYPE_INCONSISTENT",
                field="answer_expression",
                context={"failing_inputs": copy.deepcopy(inputs)},
            )
        all_candidates = single.candidates
        check_proposed_distractor_selection(single)
        check_distractors(single)
        return (inputs, actual, all_candidates)

    rows = run.check(candidate, check_case)
    context.inputs_cases = [row[0] for row in rows]
    context.canonical_answers = [row[1] for row in rows]
    context.eligible_indices = list(range(len(rows)))
    for c in context.candidates:
        samples = [row[2][c.index] for row in rows]
        c.rejection = next((s.rejection for s in samples if s.rejection), None)
        if c.rejection is None:
            c.values = [s.values[0] for s in samples]
    # One recipe subset must work across all samples, not a new subset per case.
    try:
        check_proposed_distractor_selection(context)
        check_distractors(context)
    except ValidationFailure as exc:
        exc.context.update(run.details())
        raise
    return {
        **run.details(),
        "selected_distractors": [
            recipe.model_dump(mode="json") for recipe in context.template.distractors
        ],
    }


def require_features(
    candidate: CodeTemplateCandidate, required: list[CodeFeature]
) -> dict[str, Any]:
    context = CodeValidationContext(candidate)
    check_structure(context)
    observed = extract_code_features(
        context.template.code, context.template.entry_function
    )
    missing = sorted(set(required) - observed)
    if missing:
        raise ValidationFailure(
            "Required code features are missing: " + ", ".join(missing),
            code="REQUIRED_FEATURE_MISSING",
            field="code",
            context={
                "required": sorted(set(required)),
                "observed": sorted(observed),
                "missing": missing,
            },
        )
    return {
        "required": sorted(set(required)),
        "observed": sorted(observed),
    }
