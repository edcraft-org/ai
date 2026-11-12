"""Single trusted registry for the eleven mathematics kernel contracts.

The mathematics is owned by the three developer-authored domain modules:

* :mod:`calculus_checks` (antiderivative, definite integral, differentiation)
* :mod:`algebra_checks` (expand, factor, complete square, linear system)
* :mod:`matrix_checks` (multiply, determinant, inverse, LU)

This module performs no mathematics. It validates that every contract id is
declared exactly once, records the actual domain-specific bounds and dispatches
the agreed JSON-compatible dict API to the owning module. There is deliberately
no optional import, fallback kernel or first-wins behaviour: a missing or
duplicated contract is a startup error.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any

from hypothesis import strategies as st
from pydantic import BaseModel

from edcraft_validator.application.check_pilot import (
    algebra_checks,
    calculus_checks,
    matrix_checks,
)
from edcraft_validator.application.check_pilot.models import (
    KernelAnswerType,
    KernelContractScope,
    KernelOperation,
    RequiredPolicy,
)

KERNEL_CONTRACT_IDS: tuple[str, ...] = (
    "polynomial.antiderivative/1",
    "polynomial.definite-integral/1",
    "expression.differentiate/1",
    "polynomial.expand/1",
    "polynomial.factor/1",
    "polynomial.complete-square/1",
    "linear-system.unique/1",
    "matrix.multiply/1",
    "matrix.determinant/1",
    "matrix.inverse/1",
    "matrix.lu/1",
)

_KERNEL_MODULES: tuple[ModuleType, ...] = (
    calculus_checks,
    algebra_checks,
    matrix_checks,
)

_REQUIRED_API = (
    "CONTRACT_SPECS",
    "PROBLEM_TYPES",
    "validate_problem",
    "expected_answer",
    "check_answer",
    "wrong_answers",
    "render_problem",
    "render_answer",
    "problem_strategy",
    "boundary_problems",
    "problem_extent",
)

_REQUIRED_POLICY: tuple[RequiredPolicy, ...] = (
    "complete_correctness",
    "independent_correctness",
    "all_options_checked",
)

# Domain-specific task metadata and bounds owned by the concrete kernels.
# Bounds use their exported constants and are never inferred from model data.
_CATALOG: dict[str, dict[str, Any]] = {
    "polynomial.antiderivative/1": {
        "module": calculus_checks,
        "operation": "antiderivative",
        "answer_type": "antiderivative",
        "min_degree": 0,
        "max_degree": calculus_checks.MAX_DEGREE,
        "max_abs_coefficient": calculus_checks.MAX_ABS_COEFFICIENT,
        "min_dimension": 0,
        "max_dimension": 0,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "polynomial.definite-integral/1": {
        "module": calculus_checks,
        "operation": "definite-integral",
        "answer_type": "scalar",
        "min_degree": 0,
        "max_degree": calculus_checks.MAX_DEGREE,
        "max_abs_coefficient": calculus_checks.MAX_ABS_COEFFICIENT,
        "min_dimension": 0,
        "max_dimension": 0,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "expression.differentiate/1": {
        "module": calculus_checks,
        "operation": "differentiate-expression",
        "answer_type": "expression",
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": calculus_checks.MAX_ABS_COEFFICIENT,
        "min_dimension": 0,
        "max_dimension": 0,
        "requires_general": False,
        "domain_assumptions": (
            "Every declared symbol is real; positive implies nonzero.",
        ),
    },
    "polynomial.expand/1": {
        "module": algebra_checks,
        "operation": "expand",
        "answer_type": "expression",
        "min_degree": 1,
        "max_degree": algebra_checks.MAX_PROBLEM_DEGREE,
        "max_abs_coefficient": algebra_checks.MAX_EXPANDED_COEFFICIENT,
        "min_dimension": 0,
        "max_dimension": 0,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "polynomial.factor/1": {
        "module": algebra_checks,
        "operation": "factor",
        "answer_type": "expression",
        "min_degree": 1,
        "max_degree": algebra_checks.MAX_FACTOR_DEGREE,
        "max_abs_coefficient": algebra_checks.MAX_EXPANDED_COEFFICIENT,
        "min_dimension": 0,
        "max_dimension": 0,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "polynomial.complete-square/1": {
        "module": algebra_checks,
        "operation": "complete-square",
        "answer_type": "expression",
        "min_degree": 2,
        "max_degree": 2,
        "max_abs_coefficient": algebra_checks.MAX_EXPANDED_COEFFICIENT,
        "min_dimension": 0,
        "max_dimension": 0,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "linear-system.unique/1": {
        "module": algebra_checks,
        "operation": "solve-linear-system",
        "answer_type": "tuple",
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": algebra_checks.MAX_SYSTEM_ENTRY,
        "min_dimension": 2,
        "max_dimension": 2,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "matrix.multiply/1": {
        "module": matrix_checks,
        "operation": "matrix-multiply",
        "answer_type": "matrix",
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": matrix_checks.MAX_ENTRY_ABS,
        "min_dimension": 1,
        "max_dimension": max(matrix_checks.MAX_ROWS, matrix_checks.MAX_COLUMNS),
        "requires_general": False,
        "domain_assumptions": (),
    },
    "matrix.determinant/1": {
        "module": matrix_checks,
        "operation": "matrix-determinant",
        "answer_type": "scalar",
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": matrix_checks.MAX_ENTRY_ABS,
        "min_dimension": 2,
        "max_dimension": matrix_checks.MAX_SQUARE_SIZE,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "matrix.inverse/1": {
        "module": matrix_checks,
        "operation": "matrix-inverse",
        "answer_type": "matrix",
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": matrix_checks.MAX_ENTRY_ABS,
        "min_dimension": 2,
        "max_dimension": matrix_checks.MAX_SQUARE_SIZE,
        "requires_general": False,
        "domain_assumptions": (),
    },
    "matrix.lu/1": {
        "module": matrix_checks,
        "operation": "matrix-lu",
        "answer_type": "lu-decomposition",
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": matrix_checks.MAX_ENTRY_ABS,
        "min_dimension": 2,
        "max_dimension": matrix_checks.MAX_SQUARE_SIZE,
        "requires_general": False,
        "domain_assumptions": (),
    },
}


@dataclass(frozen=True, slots=True)
class KernelContractSpec:
    """Developer-owned capability descriptor for one kernel contract."""

    contract_id: str
    kind: str
    title: str
    summary: str
    operation: KernelOperation
    answer_type: KernelAnswerType
    min_degree: int
    max_degree: int
    max_abs_coefficient: int
    min_dimension: int
    max_dimension: int
    requires_general: bool
    required_policy: tuple[RequiredPolicy, ...]
    domain_assumptions: tuple[str, ...]
    module: ModuleType

    @property
    def operation_set(self) -> str:
        return "structured-check/1"

    @property
    def relations(self) -> tuple[str, ...]:
        return ("none",)

    @property
    def template_min_degree(self) -> int:
        return self.min_degree

    def scope(self) -> KernelContractScope:
        return KernelContractScope(
            contract_id=self.contract_id,
            operation=self.operation,
            answer_type=self.answer_type,
            min_degree=self.min_degree,
            max_degree=self.max_degree,
            max_abs_coefficient=self.max_abs_coefficient,
            min_dimension=self.min_dimension,
            max_dimension=self.max_dimension,
            requires_general_antiderivative=(
                self.operation == "antiderivative" and self.requires_general
            ),
            domain_assumptions=list(self.domain_assumptions),
            required_policy=list(self.required_policy),
        )

    def descriptor(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "title": self.title,
            "summary": self.summary,
            "operation": self.operation,
            "operation_set": self.operation_set,
            "relations": list(self.relations),
            "min_degree": self.min_degree,
            "check_min_degree": self.min_degree,
            "max_degree": self.max_degree,
            "max_abs_coefficient": self.max_abs_coefficient,
            "min_dimension": self.min_dimension,
            "max_dimension": self.max_dimension,
            "answer_type": self.answer_type,
            "domain_assumptions": list(self.domain_assumptions),
            "required_policy": list(self.required_policy),
        }


def _build_registry() -> tuple[
    tuple[KernelContractSpec, ...],
    dict[str, KernelContractSpec],
    tuple[type[BaseModel], ...],
]:
    expected = set(KERNEL_CONTRACT_IDS)
    seen: dict[str, int] = {}
    problem_types: list[type[BaseModel]] = []
    for module in _KERNEL_MODULES:
        missing = [name for name in _REQUIRED_API if not hasattr(module, name)]
        if missing:
            raise RuntimeError(
                f"{module.__name__} does not expose the kernel API: {missing}"
            )
        for spec in module.CONTRACT_SPECS:
            contract_id = spec.get("contract_id")
            if not isinstance(contract_id, str) or contract_id not in expected:
                raise RuntimeError(
                    f"{module.__name__} declares an unknown contract {contract_id!r}"
                )
            seen[contract_id] = seen.get(contract_id, 0) + 1
        problem_types.extend(module.PROBLEM_TYPES)
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise RuntimeError(f"duplicate kernel contract ids: {duplicates}")
    missing = sorted(expected - set(seen))
    if missing:
        raise RuntimeError(f"missing kernel contract ids: {missing}")

    registry: dict[str, KernelContractSpec] = {}
    for contract_id in KERNEL_CONTRACT_IDS:
        metadata = _CATALOG[contract_id]
        module = metadata["module"]
        declared = {spec["contract_id"]: spec for spec in module.CONTRACT_SPECS}[
            contract_id
        ]
        registry[contract_id] = KernelContractSpec(
            contract_id=contract_id,
            kind=str(declared["kind"]),
            title=str(declared["title"]),
            summary=str(declared["summary"]),
            operation=metadata["operation"],
            answer_type=metadata["answer_type"],
            min_degree=metadata["min_degree"],
            max_degree=metadata["max_degree"],
            max_abs_coefficient=metadata["max_abs_coefficient"],
            min_dimension=metadata["min_dimension"],
            max_dimension=metadata["max_dimension"],
            requires_general=bool(metadata["requires_general"]),
            required_policy=_REQUIRED_POLICY,
            domain_assumptions=tuple(metadata["domain_assumptions"]),
            module=module,
        )
    unique_problem_types: list[type[BaseModel]] = []
    for model in problem_types:
        if model not in unique_problem_types:
            unique_problem_types.append(model)
    return (
        tuple(registry[name] for name in KERNEL_CONTRACT_IDS),
        registry,
        tuple(unique_problem_types),
    )


KERNEL_CONTRACT_SPECS, _SPEC_INDEX, KERNEL_PROBLEM_TYPES = _build_registry()


def kernel_contract_specs() -> list[KernelContractSpec]:
    return list(KERNEL_CONTRACT_SPECS)


def kernel_problem_types() -> tuple[type[BaseModel], ...]:
    return KERNEL_PROBLEM_TYPES


def kernel_contract(contract_id: object) -> KernelContractSpec | None:
    if not isinstance(contract_id, str):
        return None
    return _SPEC_INDEX.get(contract_id)


def _require_contract(contract_id: object) -> KernelContractSpec:
    spec = kernel_contract(contract_id)
    if spec is None:
        raise ValueError(f"unknown kernel contract {contract_id!r}")
    return spec


def kernel_validate_problem(
    contract_id: str, problem: dict[str, Any]
) -> dict[str, Any]:
    return _require_contract(contract_id).module.validate_problem(contract_id, problem)


def kernel_expected_answer(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    return _require_contract(contract_id).module.expected_answer(contract_id, problem)


def kernel_check_answer(
    contract_id: str, problem: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    try:
        return bool(
            _require_contract(contract_id).module.check_answer(
                contract_id, problem, candidate
            )
        )
    except (ValueError, TypeError, KeyError):
        return False


def kernel_wrong_answers(
    contract_id: str, problem: dict[str, Any], answer: dict[str, Any]
) -> list[dict[str, Any]]:
    wrongs = _require_contract(contract_id).module.wrong_answers(
        contract_id, problem, answer
    )
    return [item for item in wrongs if isinstance(item, dict)]


def kernel_render_problem(contract_id: str, problem: dict[str, Any]) -> str:
    return _require_contract(contract_id).module.render_problem(contract_id, problem)


def kernel_render_answer(contract_id: str, candidate: dict[str, Any]) -> str:
    return _require_contract(contract_id).module.render_answer(contract_id, candidate)


def kernel_problem_strategy(
    contract_id: str,
) -> st.SearchStrategy[dict[str, Any]]:
    return _require_contract(contract_id).module.problem_strategy(contract_id)


def kernel_boundary_problems(contract_id: str) -> list[dict[str, Any]]:
    return list(_require_contract(contract_id).module.boundary_problems(contract_id))


def kernel_problem_extent(
    contract_id: str, problem: dict[str, Any]
) -> dict[str, int | bool]:
    """Dispatch to the owning module's semantic degree/coefficient metadata."""
    return _require_contract(contract_id).module.problem_extent(contract_id, problem)


__all__ = [
    "KERNEL_CONTRACT_IDS",
    "KERNEL_CONTRACT_SPECS",
    "KERNEL_PROBLEM_TYPES",
    "KernelContractSpec",
    "kernel_boundary_problems",
    "kernel_check_answer",
    "kernel_contract",
    "kernel_contract_specs",
    "kernel_expected_answer",
    "kernel_problem_extent",
    "kernel_problem_strategy",
    "kernel_problem_types",
    "kernel_render_answer",
    "kernel_render_problem",
    "kernel_validate_problem",
    "kernel_wrong_answers",
]
