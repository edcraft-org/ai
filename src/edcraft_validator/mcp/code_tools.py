"""FastMCP-facing tools for deterministic code-template validation."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.domains.code.checks.answer_checks import (
    check_canonical_answers,
    check_expressions,
    check_proposed_answers,
)
from edcraft_validator.domains.code.checks.distractor_checks import (
    check_distractors,
    check_proposed_distractor_selection,
)
from edcraft_validator.domains.code.checks.execution_check import ExecutionCheck
from edcraft_validator.domains.code.checks.structure_checks import (
    check_rendering,
    check_structure,
)
from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.domains.code.code_features import extract_code_features
from edcraft_validator.domains.code.code_schemas import (
    MAX_TEMPLATE_CASES,
    CodeTemplateCandidate,
)
from edcraft_validator.domains.code.code_types import CodeFeature
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.validation_contracts import (
    AssuranceLevel,
    ValidationFailure,
)
from edcraft_validator.value_comparison import equivalent

CODE_TOOL_VERSION = "1.0.1"
STATIC_TOOL_TIMEOUT_SECONDS = 5.0


_EXECUTION_ERROR_CODES = {
    "CHECK_TIMEOUT",
    "EXECUTION_TIMEOUT",
    "EXECUTOR_PROTOCOL_ERROR",
    "INVALID_TOOL_OUTPUT",
    "RESOURCE_LIMIT_EXCEEDED",
    "TOOL_FAILURE",
    "TRACE_LIMIT_EXCEEDED",
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
) -> None:
    """Register the authoritative code-validation catalogue on ``server``."""
    execution_timeout = timeout_seconds * MAX_TEMPLATE_CASES + 2

    @server.tool(
        name="code_verify_template_structure",
        version=CODE_TOOL_VERSION,
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
            "for every input. It performs bounded static and expression checks only; "
            "it does not execute the program or establish that answers are correct."
        ),
    )
    async def code_verify_template_structure(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        def operation() -> dict[str, Any]:
            context = CodeValidationContext(candidate)
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

        return await _run_tool(
            "code_verify_template_structure",
            "bounded",
            operation,
            timeout_seconds=STATIC_TOOL_TIMEOUT_SECONDS,
        )

    @server.tool(
        name="code_validate_answers_and_distractors",
        version=CODE_TOOL_VERSION,
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Select this tool when canonical answers and usable MCQ distractors must "
            "be established. It checks the template, executes every finite parameter "
            f"case in an isolated worker with a {timeout_seconds:g}-second per-case "
            "timeout, compares the proposed answer with traced execution, then checks "
            "that enough model-proposed distractors are distinct, type-compatible, "
            "and never equal the answer. A wrong proposed answer or insufficient "
            "valid distractors fails the call; no correction or fallback is inserted. "
            "Evidence is exhaustive only over the declared finite parameter domain. "
            "Execution is limited to the supported Python subset and a bounded trace; "
            "timeout, trace-limit, or resource-limit termination produces error "
            "evidence rather than validation failure."
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
        def operation() -> dict[str, Any]:
            context = CodeValidationContext(
                candidate, num_distractors=required_distractors
            )
            check_structure(context)
            check_expressions(context)
            check_proposed_answers(context)
            ExecutionCheck(execution_tool, timeout_seconds).run(context)
            check_canonical_answers(context)

            mismatches = [
                {
                    "inputs": copy.deepcopy(inputs),
                    "proposed": copy.deepcopy(proposed),
                    "actual": copy.deepcopy(actual),
                    "trace_summary": copy.deepcopy(execution.trace_summary),
                }
                for inputs, proposed, actual, execution in zip(
                    context.inputs_cases,
                    context.proposed_answers,
                    context.canonical_answers,
                    context.executions,
                    strict=True,
                )
                if not equivalent(proposed, actual)
            ]
            if mismatches:
                raise ValidationFailure(
                    "The proposed answer disagrees with traced execution for "
                    f"{len(mismatches)} of {len(context.inputs_cases)} cases",
                    code="PROPOSED_ANSWER_MISMATCH",
                    field="answer_expression",
                    context={
                        "cases": len(context.inputs_cases),
                        "mismatches": mismatches,
                    },
                )

            check_proposed_distractor_selection(context)
            check_distractors(context)
            return {
                **context.case_details,
                "canonical_answers": [
                    {
                        "inputs": copy.deepcopy(inputs),
                        "answer": copy.deepcopy(answer),
                        "trace_summary": copy.deepcopy(execution.trace_summary),
                    }
                    for inputs, answer, execution in zip(
                        context.inputs_cases,
                        context.canonical_answers,
                        context.executions,
                        strict=True,
                    )
                ],
                "selected_distractors": [
                    recipe.model_dump(mode="json")
                    for recipe in context.template.distractors
                ],
            }

        return await _run_tool(
            "code_validate_answers_and_distractors",
            "exhaustive",
            operation,
            timeout_seconds=execution_timeout,
        )

    @server.tool(
        name="code_require_features",
        version=CODE_TOOL_VERSION,
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Select this tool when the authoring request requires concrete Python "
            "features such as a loop, conditional, helper function, or list operation. "
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
                description="Features that must occur in reachable learner code.",
            ),
        ],
    ) -> ToolEvidence:
        def operation() -> dict[str, Any]:
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

        return await _run_tool(
            "code_require_features",
            "bounded",
            operation,
            timeout_seconds=STATIC_TOOL_TIMEOUT_SECONDS,
        )


async def _run_tool(
    name: str,
    assurance: AssuranceLevel,
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
            assurance=assurance,
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
            assurance,
            started,
            code="CHECK_TIMEOUT",
            message="Validation tool exceeded its execution timeout",
        )
    except Exception as exc:
        return _unexpected_error(
            name,
            assurance,
            started,
            code="TOOL_EXECUTION_ERROR",
            message=f"Validation tool failed with {type(exc).__name__}",
        )
    return ToolEvidence(
        tool=name,
        version=CODE_TOOL_VERSION,
        status="passed",
        assurance=assurance,
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def _unexpected_error(
    name: str,
    assurance: AssuranceLevel,
    started: float,
    *,
    code: str,
    message: str,
) -> ToolEvidence:
    return ToolEvidence(
        tool=name,
        version=CODE_TOOL_VERSION,
        status="error",
        assurance=assurance,
        findings=[ToolFinding(code=code, message=message)],
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
