"""Generic structured-problem binding, scope and generation support.

This module contains no kernel mathematics. It applies bounded numeric bindings
to an already validated kernel problem, checks the instantiated problem against
the stored contract scope, and builds guarded multiple-choice instances from the
registry's independent expected-answer and wrong-answer API.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from edcraft_validator.application.check_pilot.kernel_registry import (
    KernelContractSpec,
    kernel_check_answer,
    kernel_contract,
    kernel_expected_answer,
    kernel_problem_extent,
    kernel_problem_types,
    kernel_render_answer,
    kernel_render_problem,
    kernel_validate_problem,
    kernel_wrong_answers,
)
from edcraft_validator.application.check_pilot.models import (
    KernelContractScope,
    KernelGoal,
    StructuredProblemFamily,
)

if TYPE_CHECKING:
    from hypothesis import strategies as st

_METADATA_KEYS = frozenset({"kind", "op", "sym", "variable"})


class StructuredFamilyError(ValueError):
    """A structured family or binding is outside the trusted kernel surface."""


@dataclass(frozen=True, slots=True)
class ProblemExtent:
    min_degree: int
    max_degree: int
    max_abs_coefficient: int
    min_dimension: int
    max_dimension: int
    requires_general: bool


@dataclass(frozen=True, slots=True)
class StructuredGeneratedInstance:
    problem: dict[str, Any]
    expected: dict[str, Any]
    expression: str
    question: str
    choices: tuple[str, ...]
    correct_index: int
    parameters: dict[str, int | str]
    distractors: tuple[dict[str, Any], ...]
    answer: str


def kernel_problem_schema_fragment() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A closed model-facing union for the authored kernel problem object."""
    any_of: list[dict[str, Any]] = []
    definitions: dict[str, Any] = {}
    for model in kernel_problem_types():
        name = model.__name__
        schema = model.model_json_schema()
        any_of.append({"$ref": f"#/$defs/{name}"})
        body = {key: value for key, value in schema.items() if key != "$defs"}
        definitions.setdefault(name, body)
        nested = schema.get("$defs")
        if isinstance(nested, dict):
            for key, value in nested.items():
                definitions.setdefault(key, value)
    return any_of, definitions


def _segments(path: str) -> list[str]:
    return path.split(".")


def _check_path(path: str) -> list[str]:
    segments = _segments(path)
    if not segments or any(not segment for segment in segments):
        raise StructuredFamilyError("binding path is empty")
    for segment in segments:
        if segment in _METADATA_KEYS:
            raise StructuredFamilyError(
                f"binding path {path!r} addresses metadata, not numeric data"
            )
        if not segment.isdigit() and not (segment[0].isalpha() or segment[0] == "_"):
            raise StructuredFamilyError(f"binding path {path!r} is invalid")
    return segments


def _resolve(problem: Any, path: str) -> tuple[Any, str | int, Any]:
    segments = _check_path(path)
    current = problem
    for segment in segments[:-1]:
        if isinstance(current, dict):
            if segment not in current:
                raise StructuredFamilyError(
                    f"binding path {path!r} does not exist in the problem"
                )
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit() or int(segment) >= len(current):
                raise StructuredFamilyError(
                    f"binding path {path!r} does not exist in the problem"
                )
            current = current[int(segment)]
        else:
            raise StructuredFamilyError(f"binding path {path!r} is not traversable")
    last = segments[-1]
    if isinstance(current, dict):
        if last not in current:
            raise StructuredFamilyError(
                f"binding path {path!r} does not address a numeric leaf"
            )
        return current, last, current[last]
    if isinstance(current, list):
        if not last.isdigit() or int(last) >= len(current):
            raise StructuredFamilyError(
                f"binding path {path!r} does not address a numeric leaf"
            )
        return current, int(last), current[int(last)]
    raise StructuredFamilyError(f"binding path {path!r} is not traversable")


def _coerce_numeric(existing: Any, value: int, path: str) -> int | str:
    if type(existing) is int:
        return value
    if isinstance(existing, str):
        try:
            Fraction(existing)
        except (ValueError, ZeroDivisionError):
            raise StructuredFamilyError(
                f"binding path {path!r} does not address a numeric string"
            ) from None
        return str(value)
    raise StructuredFamilyError(
        f"binding path {path!r} does not address a numeric leaf"
    )


def apply_bindings(
    problem: dict[str, Any], assignment: dict[str, int]
) -> dict[str, Any]:
    """Return a deep copy with exact int/string numeric leaves replaced."""
    result = copy.deepcopy(problem)
    for path, value in assignment.items():
        parent, key, existing = _resolve(result, path)
        coerced = _coerce_numeric(existing, value, path)
        if isinstance(parent, dict):
            parent[key] = coerced
        else:
            parent[int(key)] = coerced
    return result


def numeric_leaf_paths(problem: Any, prefix: str = "") -> list[str]:
    """Every dotted path that addresses a genuine exact numeric leaf."""
    paths: list[str] = []
    if isinstance(problem, dict):
        for key, value in problem.items():
            if key in _METADATA_KEYS:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                paths.extend(numeric_leaf_paths(value, path))
            elif _fraction_abs(value) is not None:
                paths.append(path)
    elif isinstance(problem, list):
        for index, value in enumerate(problem):
            path = f"{prefix}.{index}" if prefix else str(index)
            if isinstance(value, (dict, list)):
                paths.extend(numeric_leaf_paths(value, path))
            elif _fraction_abs(value) is not None:
                paths.append(path)
    return paths


def _fraction_abs(value: object) -> int | None:
    if type(value) is int:
        return abs(value)
    if isinstance(value, str):
        try:
            number = Fraction(value)
        except (ValueError, ZeroDivisionError):
            return None
        return max(abs(number.numerator), number.denominator)
    return None


def problem_extent(spec: KernelContractSpec, problem: dict[str, Any]) -> ProblemExtent:
    """Use the owning domain module's actual polynomial/system metadata."""
    metadata = kernel_problem_extent(spec.contract_id, problem)
    return ProblemExtent(
        min_degree=int(metadata["min_degree"]),
        max_degree=int(metadata["max_degree"]),
        max_abs_coefficient=int(metadata["max_abs_coefficient"]),
        min_dimension=int(metadata["min_dimension"]),
        max_dimension=int(metadata["max_dimension"]),
        requires_general=bool(metadata["requires_general"]),
    )


def extent_scope_findings(
    extent: ProblemExtent,
    *,
    min_degree: int,
    max_degree: int,
    max_abs_coefficient: int,
    min_dimension: int,
    max_dimension: int,
) -> list[str]:
    """Compare one computed problem extent with exact scope bounds."""
    findings: list[str] = []
    if extent.min_degree < min_degree:
        findings.append("problem degree is below the check scope")
    if extent.max_degree > max_degree:
        findings.append("problem degree exceeds the check scope")
    if extent.max_abs_coefficient > max_abs_coefficient:
        findings.append("problem coefficient exceeds the check scope")
    if extent.min_dimension < min_dimension:
        findings.append("problem dimension is below the check scope")
    if extent.max_dimension > max_dimension:
        findings.append("problem dimension exceeds the check scope")
    return findings


def problem_scope_findings(
    scope: KernelContractScope, problem: dict[str, Any]
) -> list[str]:
    """Check every concrete problem leaf against the stored scope."""
    spec = kernel_contract(scope.contract_id)
    if spec is None:
        return ["stored check scope is not a trusted kernel contract"]
    if scope.operation != spec.operation or scope.answer_type != spec.answer_type:
        return ["stored check scope does not match its trusted contract"]
    try:
        extent = problem_extent(spec, problem)
    except ValueError as exc:
        return [f"problem is outside the trusted kernel contract: {str(exc)[:300]}"]
    return extent_scope_findings(
        extent,
        min_degree=scope.min_degree,
        max_degree=scope.max_degree,
        max_abs_coefficient=scope.max_abs_coefficient,
        min_dimension=scope.min_dimension,
        max_dimension=scope.max_dimension,
    )


def problem_goal_findings(
    contract_id: str, goal: KernelGoal, problem: dict[str, Any]
) -> list[str]:
    """Compare one concrete problem with the task goal, not just contract bounds."""
    spec = kernel_contract(contract_id)
    if spec is None:
        return ["the goal names an unknown kernel contract"]
    try:
        extent = problem_extent(spec, problem)
    except ValueError as exc:
        return [f"problem is outside the trusted kernel contract: {str(exc)[:300]}"]
    findings = extent_scope_findings(
        extent,
        min_degree=goal.min_degree,
        max_degree=goal.max_degree,
        max_abs_coefficient=goal.max_abs_coefficient,
        min_dimension=goal.min_dimension,
        max_dimension=goal.max_dimension,
    )
    if extent.requires_general != goal.requires_general_antiderivative:
        findings.append("problem antiderivative form does not match the requested goal")
    return findings


def boundary_assignments(
    family: StructuredProblemFamily,
) -> list[dict[str, int]]:
    """First/last plus every single-binding value, deduplicated.

    Varying one binding at a time reaches interior values such as a zero
    coefficient in ``[-1, 0, 1]`` without enumerating the full product.
    """
    if not family.bindings:
        return [{}]
    base = {binding.path: binding.values[0] for binding in family.bindings}
    last = {binding.path: binding.values[-1] for binding in family.bindings}
    items = [base, last]
    for binding in family.bindings:
        for value in binding.values:
            changed = dict(base)
            changed[binding.path] = value
            items.append(changed)
    unique: dict[str, dict[str, int]] = {}
    for item in items:
        unique[json.dumps(item, sort_keys=True)] = item
    return list(unique.values())


def family_assignment_count(family: StructuredProblemFamily) -> int:
    size = 1
    for binding in family.bindings:
        size *= len(binding.values)
    return size


def sampled_assignments(
    family: StructuredProblemFamily, *, seed: int, limit: int
) -> list[dict[str, int]]:
    """Deterministically sample binding assignments without enumerating huge sets."""
    if not family.bindings:
        return [{}] if limit > 0 else []
    rng = random.Random(seed)
    seen: set[str] = set()
    items: list[dict[str, int]] = []
    for assignment in boundary_assignments(family):
        if len(items) >= limit:
            break
        key = json.dumps(assignment, sort_keys=True)
        if key not in seen:
            seen.add(key)
            items.append(assignment)
    attempts = 0
    while len(items) < limit and attempts < limit * 20:
        attempts += 1
        assignment = {
            binding.path: rng.choice(binding.values) for binding in family.bindings
        }
        key = json.dumps(assignment, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        items.append(assignment)
    return items


def validate_structured_family(family: StructuredProblemFamily) -> None:
    """Validate the closed problem, every binding path and all boundary cases."""
    spec = kernel_contract(family.contract_id)
    if spec is None:
        raise ValueError("the structured family names an unknown kernel contract")
    try:
        kernel_validate_problem(spec.contract_id, family.problem)
    except ValueError as exc:
        raise ValueError(f"structured problem is invalid: {exc}") from None
    paths = [binding.path for binding in family.bindings]
    if len(set(paths)) != len(paths):
        raise ValueError("structured family binding paths must be unique")
    scope = spec.scope()
    for binding in family.bindings:
        _, _, existing = _resolve(family.problem, binding.path)
        _coerce_numeric(existing, binding.values[0], binding.path)
    for assignment in boundary_assignments(family):
        try:
            concrete = apply_bindings(family.problem, assignment)
            kernel_validate_problem(spec.contract_id, concrete)
        except (ValueError, StructuredFamilyError) as exc:
            raise ValueError(
                f"a bound instance is outside the kernel contract: {exc}"
            ) from None
        findings = problem_scope_findings(scope, concrete)
        if findings:
            raise ValueError(
                f"a bound instance is outside the check scope: {findings[0]}"
            )


def structured_family_goal(family: StructuredProblemFamily) -> KernelGoal:
    """Derive the concrete plan goal from the family and all bound boundary cases."""
    spec = kernel_contract(family.contract_id)
    if spec is None:
        raise ValueError("the structured family names an unknown kernel contract")
    extents = [
        problem_extent(spec, apply_bindings(family.problem, assignment))
        for assignment in boundary_assignments(family)
    ]
    general = {extent.requires_general for extent in extents}
    if len(general) != 1:
        raise ValueError("structured family mixes general and one-primitive answers")
    return KernelGoal(
        operation=spec.operation,
        answer_type=spec.answer_type,
        min_degree=min(extent.min_degree for extent in extents),
        max_degree=max(extent.max_degree for extent in extents),
        max_abs_coefficient=max(extent.max_abs_coefficient for extent in extents),
        min_dimension=min(extent.min_dimension for extent in extents),
        max_dimension=max(extent.max_dimension for extent in extents),
        requires_general_antiderivative=general.pop(),
        domain_assumptions=list(spec.domain_assumptions),
    )


def _distinct_distractors(
    spec: KernelContractSpec,
    problem: dict[str, Any],
    expected: dict[str, Any],
    answer_text: str,
    required: int,
    *,
    seed: int,
) -> tuple[dict[str, Any], ...]:
    wrongs = kernel_wrong_answers(spec.contract_id, problem, expected)
    rng = random.Random(seed)
    rng.shuffle(wrongs)
    selected: list[dict[str, Any]] = []
    rendered = {answer_text}
    for wrong in wrongs:
        try:
            text = kernel_render_answer(spec.contract_id, wrong)
        except (ValueError, TypeError):
            continue
        if text in rendered:
            continue
        rendered.add(text)
        selected.append(wrong)
        if len(selected) >= required:
            break
    if len(selected) < required:
        raise StructuredFamilyError(
            "the bounded wrong-answer set could not supply distinct distractors"
        )
    return tuple(selected)


def build_instance(
    family: StructuredProblemFamily,
    assignment: dict[str, int],
    *,
    seed: int,
    scope: KernelContractScope | None = None,
) -> StructuredGeneratedInstance:
    """Build one guarded instance from a validated binding assignment."""
    spec = kernel_contract(family.contract_id)
    if spec is None:
        raise StructuredFamilyError("the structured family names an unknown contract")
    problem = apply_bindings(family.problem, assignment)
    kernel_validate_problem(spec.contract_id, problem)
    findings = problem_scope_findings(scope or spec.scope(), problem)
    if findings:
        raise StructuredFamilyError(findings[0])
    expected = kernel_expected_answer(spec.contract_id, problem)
    answer_text = kernel_render_answer(spec.contract_id, expected)
    if not kernel_check_answer(spec.contract_id, problem, expected):
        raise StructuredFamilyError("the kernel rejected its own expected answer")
    distractors = _distinct_distractors(
        spec,
        problem,
        expected,
        answer_text,
        family.num_distractors,
        seed=seed,
    )
    choice_texts = [
        answer_text,
        *(kernel_render_answer(spec.contract_id, item) for item in distractors),
    ]
    if len(set(choice_texts)) != len(choice_texts):
        raise StructuredFamilyError("generated choices are not distinct")
    choices = list(choice_texts)
    rng = random.Random(seed)
    rng.shuffle(choices)
    correct_index = choices.index(answer_text)
    problem_text = kernel_render_problem(spec.contract_id, problem)
    parameters: dict[str, int | str] = {
        binding.path: assignment[binding.path] for binding in family.bindings
    }
    parameters["contract_id"] = spec.contract_id
    return StructuredGeneratedInstance(
        problem=problem,
        expected=expected,
        expression=problem_text,
        question=problem_text,
        choices=tuple(choices),
        correct_index=correct_index,
        parameters=parameters,
        distractors=distractors,
        answer=answer_text,
    )


def guard_instance(
    instance: StructuredGeneratedInstance,
    *,
    contract_id: str,
    num_distractors: int,
    scope: KernelContractScope | None = None,
) -> list[str]:
    """Independent guard over structured values; no rendered answer is parsed."""
    spec = kernel_contract(contract_id)
    if spec is None:
        return ["the generated instance names an unknown kernel contract"]
    findings: list[str] = []
    try:
        expected = kernel_expected_answer(contract_id, instance.problem)
    except ValueError as exc:
        return [f"kernel rejected the generated problem: {exc}"]
    findings.extend(problem_scope_findings(scope or spec.scope(), instance.problem))
    if expected != instance.expected:
        findings.append("expected answer disagrees with the kernel oracle")
    answer_text = kernel_render_answer(contract_id, expected)
    if instance.answer != answer_text:
        findings.append("rendered answer does not match the kernel answer")
    if len(instance.choices) != num_distractors + 1:
        findings.append("choice count does not match the requested distractors")
    if len(set(instance.choices)) != len(instance.choices):
        findings.append("choice options are not distinct")
    if not 0 <= instance.correct_index < len(instance.choices):
        findings.append("correct index does not address a choice")
    elif instance.choices[instance.correct_index] != answer_text:
        findings.append("the keyed choice is not the kernel answer")
    if not kernel_check_answer(contract_id, instance.problem, expected):
        findings.append("the kernel rejected the independently derived answer")
    for distractor in instance.distractors:
        if kernel_check_answer(contract_id, instance.problem, distractor):
            findings.append("a distractor is accepted by the kernel")
        try:
            text = kernel_render_answer(contract_id, distractor)
        except ValueError:
            findings.append("a distractor cannot be rendered")
            continue
        if text == answer_text:
            findings.append("a distractor renders as the correct answer")
        if text not in instance.choices:
            findings.append("a rendered distractor is missing from the options")
    if instance.question != kernel_render_problem(contract_id, instance.problem):
        findings.append("the rendered question does not match the problem")
    return findings


def structured_problem_strategy(
    contract_id: str,
) -> st.SearchStrategy[dict[str, Any]]:
    from edcraft_validator.application.check_pilot.kernel_registry import (
        kernel_problem_strategy,
    )

    return kernel_problem_strategy(contract_id)


__all__ = [
    "ProblemExtent",
    "StructuredFamilyError",
    "StructuredGeneratedInstance",
    "apply_bindings",
    "boundary_assignments",
    "build_instance",
    "extent_scope_findings",
    "family_assignment_count",
    "guard_instance",
    "kernel_problem_schema_fragment",
    "numeric_leaf_paths",
    "problem_extent",
    "problem_goal_findings",
    "problem_scope_findings",
    "sampled_assignments",
    "structured_family_goal",
    "structured_problem_strategy",
    "validate_structured_family",
]
