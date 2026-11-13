"""Trusted registry for the eleven deterministic-engine check contracts.

Each engine contract is an authoritative grading capability for exactly one
existing pilot kernel contract.  The kernel contract keeps generating bounded
problems, expected answers and distractors; the engine grades the problem and
candidate answer with its own closed IR and never falls back to the kernel
verdict.  This module records that pairing and performs no mathematics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edcraft_validator.application.check_pilot.kernel_registry import (
    KERNEL_CONTRACT_IDS,
    KernelContractSpec,
    kernel_contract,
)
from edcraft_validator.application.check_pilot.models import (
    EngineCheckDefinition,
    EngineContractScope,
    EngineOperation,
    RequiredPolicy,
)

ENGINE_CONTRACT_IDS: tuple[str, ...] = tuple(
    f"engine.{contract_id}" for contract_id in KERNEL_CONTRACT_IDS
)

# The engine operation that grades each pilot kernel contract.  The kernel
# operation and answer type stay on the scope so plan/template applicability is
# unchanged; only grading is reassigned.
_ENGINE_OPERATIONS: dict[str, EngineOperation] = {
    "polynomial.antiderivative/1": "antiderivative",
    "polynomial.definite-integral/1": "definite-integral",
    "expression.differentiate/1": "differentiate",
    "polynomial.expand/1": "expand",
    "polynomial.factor/1": "factor",
    "polynomial.complete-square/1": "complete-square",
    "linear-system.unique/1": "solve",
    "matrix.multiply/1": "matrix-multiply",
    "matrix.determinant/1": "determinant",
    "matrix.inverse/1": "inverse",
    "matrix.lu/1": "lu",
}

_REQUIRED_POLICY: tuple[RequiredPolicy, ...] = (
    "complete_correctness",
    "independent_correctness",
    "all_options_checked",
)


@dataclass(frozen=True, slots=True)
class EngineContractSpec:
    """Developer-owned pairing of one engine grader with one kernel generator."""

    contract_id: str
    generator: KernelContractSpec
    operation: EngineOperation
    required_policy: tuple[RequiredPolicy, ...] = _REQUIRED_POLICY

    @property
    def generator_contract_id(self) -> str:
        return self.generator.contract_id

    @property
    def kind(self) -> str:
        return self.generator.kind

    @property
    def title(self) -> str:
        return f"Engine-graded: {self.generator.title}"

    @property
    def summary(self) -> str:
        return (
            f"{self.generator.summary} The deterministic engine grades the "
            "candidate authoritatively; the kernel only generates and supplies "
            "agreement evidence."
        )

    @property
    def operation_set(self) -> str:
        return "structured-check/1"

    @property
    def relations(self) -> tuple[str, ...]:
        return ("none",)

    @property
    def answer_type(self) -> str:
        return self.generator.answer_type

    @property
    def min_degree(self) -> int:
        return self.generator.min_degree

    @property
    def template_min_degree(self) -> int:
        return self.generator.template_min_degree

    @property
    def max_degree(self) -> int:
        return self.generator.max_degree

    @property
    def max_abs_coefficient(self) -> int:
        return self.generator.max_abs_coefficient

    @property
    def min_dimension(self) -> int:
        return self.generator.min_dimension

    @property
    def max_dimension(self) -> int:
        return self.generator.max_dimension

    @property
    def requires_general_antiderivative(self) -> bool:
        return (
            self.generator.operation == "antiderivative"
            and self.generator.requires_general
        )

    @property
    def domain_assumptions(self) -> tuple[str, ...]:
        return self.generator.domain_assumptions

    def scope(self) -> EngineContractScope:
        return EngineContractScope(
            contract_id=self.contract_id,
            operation=self.generator.operation,
            answer_type=self.generator.answer_type,
            min_degree=self.generator.min_degree,
            max_degree=self.generator.max_degree,
            max_abs_coefficient=self.generator.max_abs_coefficient,
            min_dimension=self.generator.min_dimension,
            max_dimension=self.generator.max_dimension,
            requires_general_antiderivative=self.requires_general_antiderivative,
            domain_assumptions=list(self.generator.domain_assumptions),
            required_policy=list(self.required_policy),
            grader="engine",
            generator_contract_id=self.generator_contract_id,
        )

    def definition(self) -> EngineCheckDefinition:
        return EngineCheckDefinition(
            contract_id=self.contract_id,
            operation=self.operation,
            generator_contract_id=self.generator_contract_id,
            grader="engine",
        )

    def descriptor(self) -> dict[str, Any]:
        # ``requires_general`` is deliberately absent: consumers that inspect
        # engine descriptors use the explicit ``requires_general_antiderivative``
        # key, and the kernel catalogue keeps its own capability flag.
        return {
            "contract_id": self.contract_id,
            "title": self.title,
            "summary": self.summary,
            "operation": self.generator.operation,
            "engine_operation": self.operation,
            "operation_set": self.operation_set,
            "relations": list(self.relations),
            "min_degree": self.template_min_degree,
            "check_min_degree": self.min_degree,
            "max_degree": self.max_degree,
            "max_abs_coefficient": self.max_abs_coefficient,
            "min_dimension": self.min_dimension,
            "max_dimension": self.max_dimension,
            "requires_general_antiderivative": (self.requires_general_antiderivative),
            "answer_type": self.answer_type,
            "domain_assumptions": list(self.domain_assumptions),
            "required_policy": list(self.required_policy),
            "grader": "engine",
            "generator_contract_id": self.generator_contract_id,
        }


def _build_registry() -> tuple[
    tuple[EngineContractSpec, ...], dict[str, EngineContractSpec]
]:
    registry: dict[str, EngineContractSpec] = {}
    for kernel_id in KERNEL_CONTRACT_IDS:
        kernel = kernel_contract(kernel_id)
        if kernel is None:
            raise RuntimeError(f"missing kernel contract {kernel_id!r}")
        operation = _ENGINE_OPERATIONS.get(kernel_id)
        if operation is None:
            raise RuntimeError(f"missing engine operation for {kernel_id!r}")
        contract_id = f"engine.{kernel_id}"
        registry[contract_id] = EngineContractSpec(
            contract_id=contract_id,
            generator=kernel,
            operation=operation,
        )
    if set(registry) != set(ENGINE_CONTRACT_IDS):
        raise RuntimeError("engine contract ids are not the agreed eleven")
    return tuple(registry[name] for name in ENGINE_CONTRACT_IDS), registry


ENGINE_CONTRACT_SPECS, _SPEC_INDEX = _build_registry()


def engine_contract_specs() -> list[EngineContractSpec]:
    return list(ENGINE_CONTRACT_SPECS)


def engine_contract(contract_id: object) -> EngineContractSpec | None:
    if not isinstance(contract_id, str):
        return None
    return _SPEC_INDEX.get(contract_id)


def engine_contract_for_generator(
    generator_contract_id: object,
) -> EngineContractSpec | None:
    if not isinstance(generator_contract_id, str):
        return None
    return _SPEC_INDEX.get(f"engine.{generator_contract_id}")


__all__ = [
    "ENGINE_CONTRACT_IDS",
    "ENGINE_CONTRACT_SPECS",
    "EngineContractSpec",
    "engine_contract",
    "engine_contract_for_generator",
    "engine_contract_specs",
]
