"""MCP interfaces, deadlines, and evidence for code-domain operations."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.domains.code.code_schemas import (
    MAX_TEMPLATE_CASES,
    CodeTemplateCandidate,
)
from edcraft_validator.domains.code.code_types import CodeFeature
from edcraft_validator.domains.code.validation_operations import (
    require_features,
    validate_answers_and_distractors,
    verify_template_structure,
)
from edcraft_validator.mcp.evidence import ToolEvidence, ToolFinding
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.validation_contracts import ValidationFailure

CODE_TOOL_VERSION = "1.0.2"
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
        return await _run_tool(
            "code_verify_template_structure",
            lambda: verify_template_structure(candidate),
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
        return await _run_tool(
            "code_validate_answers_and_distractors",
            lambda: validate_answers_and_distractors(
                candidate,
                required_distractors,
                execution_tool=execution_tool,
                timeout_seconds=timeout_seconds,
            ),
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
