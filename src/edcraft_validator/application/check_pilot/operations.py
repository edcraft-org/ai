"""Trusted operation descriptors, recipe compilation, and execution.

A recipe is closed data. Compilation checks operation identity and version,
argument/output types, exact references, uniqueness, acyclic prior-step use,
scope, and size before execution. Execution only dispatches to this allowlist.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from edcraft_validator.application.check_pilot.models import (
    SUPPORTED_SCOPE,
    CheckRecipeDefinition,
    PolynomialScope,
    RecipeArgument,
    RecipeExecutionResult,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    derivative_via_sympy,
    render_polynomial,
)

ValueType = Literal["polynomial", "candidate", "integer", "verdict", "boolean"]
OperationExecutor = Callable[[dict[str, object]], object]
INPUT_TYPES: dict[str, ValueType] = {
    "problem": "polynomial",
    "candidate": "candidate",
}


def _require_polynomial(value: object) -> Polynomial:
    if not isinstance(value, Polynomial):
        raise RecipeCompileError(["operation expected polynomial data"])
    return value


def _execute_differentiate(resolved: dict[str, object]) -> object:
    return derivative_via_sympy(_require_polynomial(resolved["polynomial"]))


def _execute_identity(resolved: dict[str, object]) -> object:
    return _require_polynomial(resolved["polynomial"])


def _execute_evaluate_at(resolved: dict[str, object]) -> object:
    point = resolved["point"]
    if type(point) is not int:
        raise RecipeCompileError(["evaluation point must be an integer"])
    return _require_polynomial(resolved["polynomial"]).evaluate(point)


def _execute_equivalent(resolved: dict[str, object]) -> object:
    return _require_polynomial(resolved["expected"]) == _require_polynomial(
        resolved["actual"]
    )


def _execute_number_equal(resolved: dict[str, object]) -> object:
    return resolved["left"] == resolved["right"]


def _execute_constant_verdict(resolved: dict[str, object]) -> object:
    return bool(resolved["value"])


@dataclass(frozen=True, slots=True)
class OperationDescriptor:
    id: str
    version: str
    inputs: tuple[tuple[str, ValueType], ...]
    output: ValueType
    summary: str
    weak_reason: str | None
    execute: OperationExecutor

    def input_types(self) -> dict[str, ValueType]:
        return dict(self.inputs)


_OPERATIONS = (
    OperationDescriptor(
        id="poly.differentiate",
        version="1",
        inputs=(("polynomial", "polynomial"),),
        output="polynomial",
        summary="Differentiate one bounded univariate polynomial exactly.",
        weak_reason=None,
        execute=_execute_differentiate,
    ),
    OperationDescriptor(
        id="poly.identity",
        version="1",
        inputs=(("polynomial", "polynomial"),),
        output="polynomial",
        summary="Return its input unchanged (weak; never sufficient).",
        weak_reason=(
            "identity recipes cannot establish a derivative and are candidate-to-itself"
        ),
        execute=_execute_identity,
    ),
    OperationDescriptor(
        id="poly.evaluate_at",
        version="1",
        inputs=(("polynomial", "polynomial"), ("point", "integer")),
        output="integer",
        summary="Evaluate at one integer point (weak; never sufficient).",
        weak_reason=(
            "point sampling cannot establish polynomial equivalence in this pilot"
        ),
        execute=_execute_evaluate_at,
    ),
    OperationDescriptor(
        id="poly.equivalent",
        version="1",
        inputs=(("expected", "polynomial"), ("actual", "candidate")),
        output="verdict",
        summary=(
            "Compare a derived expected polynomial with the parsed candidate "
            "polynomial over all coefficients."
        ),
        weak_reason=None,
        execute=_execute_equivalent,
    ),
    OperationDescriptor(
        id="number.equal",
        version="1",
        inputs=(("left", "integer"), ("right", "integer")),
        output="verdict",
        summary="Compare two integers (weak; never sufficient).",
        weak_reason=(
            "point sampling or number comparison cannot establish polynomial "
            "equivalence in this pilot"
        ),
        execute=_execute_number_equal,
    ),
    OperationDescriptor(
        id="verdict.constant",
        version="1",
        inputs=(("value", "boolean"),),
        output="verdict",
        summary="Return a fixed verdict (weak; never sufficient).",
        weak_reason=(
            "constant verdict recipes are always-true or always-false instead of "
            "comparing a differentiate result"
        ),
        execute=_execute_constant_verdict,
    ),
)
_OPERATION_INDEX = {(item.id, item.version): item for item in _OPERATIONS}
MAX_RECIPE_STEPS = 8


class RecipeCompileError(ValueError):
    """A recipe is outside the trusted typed operation set."""

    def __init__(self, findings: list[str], *, unknown_capability: bool = False):
        super().__init__("; ".join(findings) or "recipe did not compile")
        self.findings = findings
        self.unknown_capability = unknown_capability


@dataclass(frozen=True, slots=True)
class CompiledRecipe:
    definition: CheckRecipeDefinition
    expected_step_id: str
    sha256: str


def operation_catalogue() -> list[dict[str, Any]]:
    """Model-facing descriptors for the check-author prompt."""
    return [
        {
            "id": item.id,
            "version": item.version,
            "inputs": dict(item.inputs),
            "output": item.output,
            "summary": item.summary,
        }
        for item in _OPERATIONS
    ]


def recipe_sha256(definition: CheckRecipeDefinition) -> str:
    return hashlib.sha256(
        json.dumps(
            definition.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _argument_type(
    argument: RecipeArgument,
    *,
    step_types: dict[str, ValueType],
    all_step_ids: set[str],
    seen_step_ids: set[str],
    argument_name: str,
    step_id: str,
) -> ValueType:
    if argument.source == "input":
        if argument.name not in INPUT_TYPES:
            raise RecipeCompileError(
                [f"argument {argument_name!r} on {step_id!r} names an unknown input"]
            )
        return INPUT_TYPES[argument.name]
    if argument.source == "step":
        name = argument.name or ""
        if name in seen_step_ids:
            return step_types[name]
        if name in all_step_ids:
            raise RecipeCompileError(
                [
                    f"argument {argument_name!r} on {step_id!r} references a "
                    "forward or non-prior step"
                ]
            )
        raise RecipeCompileError(
            [f"argument {argument_name!r} on {step_id!r} references unknown step"]
        )
    raise RecipeCompileError(
        [f"literal argument {argument_name!r} on {step_id!r} has no step/input type"]
    )


def _check_literal(argument: RecipeArgument, expected: ValueType, step_id: str) -> None:
    value = argument.value
    if expected == "integer":
        valid = type(value) is int
    elif expected == "boolean" or expected == "verdict":
        valid = type(value) is bool
    else:
        valid = False
    if not valid:
        raise RecipeCompileError(
            [f"literal argument on {step_id!r} does not match type {expected!r}"]
        )


def compile_recipe(
    definition: CheckRecipeDefinition,
    *,
    scope: PolynomialScope = SUPPORTED_SCOPE,
) -> CompiledRecipe:
    if scope.operation != "differentiate" or scope.variable != "x":
        raise RecipeCompileError(["the pilot supports differentiate on x only"])
    if len(definition.steps) > MAX_RECIPE_STEPS:
        raise RecipeCompileError(["recipe has too many steps"])
    all_step_ids = {step.id for step in definition.steps}
    if len(all_step_ids) != len(definition.steps):
        raise RecipeCompileError(["recipe step ids must be unique (duplicate id)"])

    step_types: dict[str, ValueType] = {}
    step_operations: dict[str, str] = {}
    weak: list[str] = []
    for step in definition.steps:
        key = (step.operation, step.version)
        descriptor = _OPERATION_INDEX.get(key)
        if descriptor is None:
            raise RecipeCompileError(
                [
                    f"unrecognized operation {step.operation!r} version "
                    f"{step.version!r} is development needed"
                ],
                unknown_capability=True,
            )
        expected_arguments = descriptor.input_types()
        if set(step.arguments) != set(expected_arguments):
            raise RecipeCompileError(
                [
                    f"argument names for {step.id!r} must match "
                    f"{sorted(expected_arguments)}"
                ]
            )
        for argument_name, expected_type in expected_arguments.items():
            argument = step.arguments[argument_name]
            if argument.source == "literal":
                _check_literal(argument, expected_type, step.id)
                continue
            actual_type = _argument_type(
                argument,
                step_types=step_types,
                all_step_ids=all_step_ids,
                seen_step_ids=set(step_types),
                argument_name=argument_name,
                step_id=step.id,
            )
            if actual_type != expected_type and not (
                expected_type == "polynomial" and actual_type == "candidate"
            ):
                raise RecipeCompileError(
                    [
                        f"argument {argument_name!r} on {step.id!r} has type "
                        f"{actual_type!r}, expected {expected_type!r}"
                    ]
                )
        step_types[step.id] = descriptor.output
        step_operations[step.id] = step.operation
        if descriptor.weak_reason is not None:
            weak.append(descriptor.weak_reason)

    if definition.output not in step_types:
        raise RecipeCompileError(["recipe output names an unknown step"])
    if step_types[definition.output] != "verdict":
        raise RecipeCompileError(["recipe output must be a verdict"])

    if weak:
        raise RecipeCompileError(sorted(set(weak)))

    output_step = next(
        step for step in definition.steps if step.id == definition.output
    )
    if output_step.operation != "poly.equivalent":
        raise RecipeCompileError(
            ["recipe output must compare a differentiate result with the candidate"]
        )
    expected_argument = output_step.arguments["expected"]
    actual_argument = output_step.arguments["actual"]
    if expected_argument.source != "step" or not expected_argument.name:
        raise RecipeCompileError(
            ["expected must reference a prior differentiate result"]
        )
    if step_operations.get(expected_argument.name) != "poly.differentiate":
        raise RecipeCompileError(
            ["expected must be the output of a differentiate step"]
        )
    if actual_argument.source != "input" or actual_argument.name != "candidate":
        raise RecipeCompileError(["actual must reference the candidate input"])

    return CompiledRecipe(
        definition=definition,
        expected_step_id=expected_argument.name,
        sha256=recipe_sha256(definition),
    )


def _resolve(
    argument: RecipeArgument,
    *,
    problem: Polynomial,
    candidate: Polynomial,
    values: dict[str, object],
) -> object:
    if argument.source == "input":
        return problem if argument.name == "problem" else candidate
    if argument.source == "step":
        return values[argument.name or ""]
    return argument.value


def execute_recipe(
    compiled: CompiledRecipe,
    problem: Polynomial,
    candidate: Polynomial,
) -> RecipeExecutionResult:
    values: dict[str, object] = {}
    for step in compiled.definition.steps:
        descriptor = _OPERATION_INDEX[(step.operation, step.version)]
        resolved = {
            name: _resolve(
                step.arguments[name],
                problem=problem,
                candidate=candidate,
                values=values,
            )
            for name in descriptor.input_types()
        }
        values[step.id] = descriptor.execute(resolved)
    verdict = values[compiled.definition.output]
    if type(verdict) is not bool:
        raise RecipeCompileError(["recipe output did not produce a verdict"])
    expected_value = values[compiled.expected_step_id]
    expected = _require_polynomial(expected_value)
    return RecipeExecutionResult(
        verdict=verdict,
        expected=render_polynomial(expected),
        problem=render_polynomial(problem),
        candidate=render_polynomial(candidate),
        recipe_sha256=compiled.sha256,
    )


__all__ = [
    "CompiledRecipe",
    "MAX_RECIPE_STEPS",
    "OperationDescriptor",
    "RecipeCompileError",
    "compile_recipe",
    "execute_recipe",
    "operation_catalogue",
    "recipe_sha256",
]
