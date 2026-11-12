"""Stable MCP adapter for the pilot's one validated recipe executor."""

from __future__ import annotations

import time
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.check_pilot.isolation import (
    PilotWorkerError,
    PilotWorkerTimeout,
)
from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    RecipeExecutionResult,
)
from edcraft_validator.application.check_pilot.operations import (
    RecipeCompileError,
    compile_recipe,
)
from edcraft_validator.application.check_pilot.polynomial import parse_polynomial
from edcraft_validator.application.check_pilot.qualification import (
    execute_recipe_isolated,
)
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding

CHECK_PILOT_RECIPE_TOOL = "check_pilot_execute_recipe"
CHECK_PILOT_TOOL_VERSION = "1"
DEFAULT_RECIPE_TIMEOUT_SECONDS = 10.0
MAX_RECIPE_TIMEOUT_SECONDS = 30.0
MAX_POLYNOMIAL_LENGTH = 2000


def register_check_pilot_tools(server: FastMCP) -> None:
    """Register the single stable recipe-execution adapter.

    The adapter has no owner parameter. Library resolution and owner
    authorization stay in the application; a model-supplied owner string can
    never grant access through this tool.
    """

    @server.tool(
        name=CHECK_PILOT_RECIPE_TOOL,
        version=CHECK_PILOT_TOOL_VERSION,
        tags={"domain:check-pilot", "validation:check-pilot"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Run one trusted closed check recipe against a bounded polynomial "
            "problem and candidate answer. Compilation validates operation ids, "
            "versions, argument/output types and step references; the recipe is "
            "then executed in a disposable interpreter with a hard wall-clock "
            "limit. No model-authored code is executed and no check library or "
            "owner record is accessed."
        ),
    )
    async def check_pilot_execute_recipe(
        definition: CheckRecipeDefinition,
        problem: Annotated[str, Field(min_length=1, max_length=MAX_POLYNOMIAL_LENGTH)],
        candidate: Annotated[
            str, Field(min_length=1, max_length=MAX_POLYNOMIAL_LENGTH)
        ],
        timeout_seconds: Annotated[
            float, Field(gt=0, le=MAX_RECIPE_TIMEOUT_SECONDS)
        ] = DEFAULT_RECIPE_TIMEOUT_SECONDS,
    ) -> ToolEvidence:
        started = time.perf_counter()
        try:
            compile_recipe(definition)
            result = execute_recipe_isolated(
                definition,
                parse_polynomial(problem),
                parse_polynomial(candidate),
                timeout_seconds=timeout_seconds,
            )
        except RecipeCompileError as exc:
            return _error(started, "RECIPE_INVALID", str(exc)[:500])
        except PilotWorkerTimeout:
            return _error(
                started,
                "RECIPE_TIMEOUT",
                f"recipe execution exceeded {timeout_seconds:g}s",
            )
        except PilotWorkerError as exc:
            return _error(started, "RECIPE_WORKER_ERROR", str(exc)[:500])
        except ValueError as exc:
            return _error(started, "RECIPE_INVALID", str(exc)[:500])
        return _evidence(started, result)


def _evidence(started: float, result: RecipeExecutionResult) -> ToolEvidence:
    status: Literal["passed", "failed"] = "passed" if result.verdict else "failed"
    findings = (
        []
        if result.verdict
        else [
            ToolFinding(
                code="RECIPE_REJECTED_CANDIDATE",
                message="the check recipe did not accept the candidate answer",
            )
        ]
    )
    return ToolEvidence(
        tool=CHECK_PILOT_RECIPE_TOOL,
        version=CHECK_PILOT_TOOL_VERSION,
        status=status,
        findings=findings,
        details=result.model_dump(mode="json"),
        duration_ms=_elapsed_ms(started),
    )


def _error(started: float, code: str, message: str) -> ToolEvidence:
    return ToolEvidence(
        tool=CHECK_PILOT_RECIPE_TOOL,
        version=CHECK_PILOT_TOOL_VERSION,
        status="error",
        findings=[ToolFinding(code=code, message=message)],
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


__all__ = [
    "CHECK_PILOT_RECIPE_TOOL",
    "CHECK_PILOT_TOOL_VERSION",
    "register_check_pilot_tools",
]
