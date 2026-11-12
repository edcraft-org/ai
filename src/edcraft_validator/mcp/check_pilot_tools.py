"""Stable MCP adapter for the pilot's one validated recipe executor."""

from __future__ import annotations

import json
import time
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.check_pilot.contracts import (
    scope_from_recipe_operation_set,
)
from edcraft_validator.application.check_pilot.isolation import (
    PilotWorkerError,
    PilotWorkerTimeout,
)
from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    PolynomialRelation,
    RealSolutionSet,
    RecipeExecutionResult,
)
from edcraft_validator.application.check_pilot.operations import (
    RecipeCompileError,
    compile_recipe,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    parse_polynomial,
)
from edcraft_validator.application.check_pilot.qualification import (
    execute_recipe_isolated,
)
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding

CHECK_PILOT_RECIPE_TOOL = "check_pilot_execute_recipe"
CHECK_PILOT_TOOL_VERSION = "1"
DEFAULT_RECIPE_TIMEOUT_SECONDS = 10.0
MAX_RECIPE_TIMEOUT_SECONDS = 30.0
MAX_POLYNOMIAL_LENGTH = 2000
MAX_STRUCTURED_PAYLOAD_LENGTH = 8000


def _polynomial(value: str | dict[str, Any]) -> Polynomial:
    text: object
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict) and value.get("kind") == "polynomial":
        text = value.get("text")
    else:
        raise ValueError("differentiation problems require polynomial text")
    if not isinstance(text, str) or not 1 <= len(text) <= MAX_POLYNOMIAL_LENGTH:
        raise ValueError(
            f"polynomial text must be 1 to {MAX_POLYNOMIAL_LENGTH} characters"
        )
    return parse_polynomial(text)


def _relation(value: str | dict[str, Any]) -> PolynomialRelation:
    if not isinstance(value, dict):
        raise ValueError("solve problems require structured relation data")
    payload: Any = value
    if value.get("kind") == "relation":
        payload = value.get("relation")
    try:
        return PolynomialRelation.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"invalid structured relation: {exc}") from exc


def _solution_set(value: str | dict[str, Any]) -> RealSolutionSet:
    if not isinstance(value, dict):
        raise ValueError("solve candidates require structured solution-set data")
    payload: Any = value
    if value.get("kind") == "solution_set":
        payload = value.get("solution_set")
    try:
        return RealSolutionSet.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"invalid structured solution set: {exc}") from exc


def _problem_value(
    definition: CheckRecipeDefinition, value: str | dict[str, Any]
) -> Polynomial | PolynomialRelation:
    if definition.operation_set == "polynomial-solve-real/1":
        return _relation(value)
    return _polynomial(value)


def _candidate_value(
    definition: CheckRecipeDefinition, value: str | dict[str, Any]
) -> Polynomial | RealSolutionSet:
    if definition.operation_set == "polynomial-solve-real/1":
        return _solution_set(value)
    return _polynomial(value)


def _bounded(value: str | dict[str, Any]) -> None:
    if isinstance(value, str):
        if not 1 <= len(value) <= MAX_POLYNOMIAL_LENGTH:
            raise ValueError(
                f"problem and candidate text must be 1 to {MAX_POLYNOMIAL_LENGTH} "
                "characters"
            )
        return
    if not isinstance(value, dict):
        raise ValueError("problem and candidate must be text or structured data")
    if len(json.dumps(value, allow_nan=False)) > MAX_STRUCTURED_PAYLOAD_LENGTH:
        raise ValueError("structured problem or candidate data is too large")


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
            "Run one trusted closed check recipe. Differentiation recipes accept "
            "bounded polynomial text for both values. Solve recipes accept one "
            "structured polynomial relation and one structured complete real "
            "solution set. Compilation validates operation ids, versions, "
            "argument/output types and step references; the recipe then runs in "
            "a disposable interpreter with a hard wall-clock limit. No "
            "model-authored code is executed and no check library or owner "
            "record is accessed."
        ),
    )
    async def check_pilot_execute_recipe(
        definition: CheckRecipeDefinition,
        problem: Annotated[
            str | dict[str, Any],
            Field(description="Polynomial text or structured solve relation data."),
        ],
        candidate: Annotated[
            str | dict[str, Any],
            Field(description="Polynomial text or structured solution-set data."),
        ],
        timeout_seconds: Annotated[
            float, Field(gt=0, le=MAX_RECIPE_TIMEOUT_SECONDS)
        ] = DEFAULT_RECIPE_TIMEOUT_SECONDS,
    ) -> ToolEvidence:
        started = time.perf_counter()
        try:
            scope = scope_from_recipe_operation_set(definition.operation_set)
            compile_recipe(definition, scope=scope)
            _bounded(problem)
            _bounded(candidate)
            result = execute_recipe_isolated(
                definition,
                _problem_value(definition, problem),
                _candidate_value(definition, candidate),
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
