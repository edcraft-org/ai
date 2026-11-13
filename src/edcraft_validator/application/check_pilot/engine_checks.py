"""Authoritative deterministic-engine grading with kernel agreement evidence.

This module runs inside the isolated pilot worker.  The engine verdict is the
only verdict: ``correct`` passes, ``incorrect`` fails, and every honest refusal
(``unknown``/``unsupported``/``timeout``/``error``) fails closed.  For generated
items the corresponding kernel check also runs, purely to record agreement; it
can never change the engine verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from edcraft_validator.application.check_pilot.engine_adapter import (
    EngineAdapterGap,
    form_findings,
    to_correctness_request,
)
from edcraft_validator.application.check_pilot.engine_registry import (
    EngineContractSpec,
    engine_contract,
)
from edcraft_validator.application.check_pilot.kernel_registry import (
    kernel_check_answer,
)
from edcraft_validator.domains.math.engine.contracts import Outcome
from edcraft_validator.domains.math.engine.dispatch import check_in_process

KernelVerdict = Literal["accepted", "rejected"]
_REFUSALS = frozenset({"unknown", "unsupported", "timeout", "error"})


@dataclass(frozen=True, slots=True)
class EngineGrading:
    outcome: Outcome
    reason: str
    kernel_verdict: KernelVerdict | None = None
    findings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.outcome == "correct"

    @property
    def failed(self) -> bool:
        return self.outcome == "incorrect"

    @property
    def refused(self) -> bool:
        return self.outcome in _REFUSALS


def is_refusal(outcome: str) -> bool:
    return outcome in _REFUSALS


def engine_spec(contract_id: object) -> EngineContractSpec:
    spec = engine_contract(contract_id)
    if spec is None:
        raise ValueError(f"unknown engine contract {contract_id!r}")
    return spec


def _kernel_agreement(
    spec: EngineContractSpec,
    problem: dict[str, Any],
    candidate: dict[str, Any],
    findings: list[str],
) -> KernelVerdict | None:
    try:
        accepted = kernel_check_answer(spec.generator_contract_id, problem, candidate)
    except Exception as exc:  # noqa: BLE001 - evidence must never decide
        findings.append(
            f"comparison kernel check raised {type(exc).__name__}: {str(exc)[:200]}"
        )
        return None
    return "accepted" if accepted else "rejected"


def grade_answer(
    contract_id: str,
    problem: dict[str, Any],
    candidate: dict[str, Any],
    *,
    compare_kernel: bool = True,
) -> EngineGrading:
    """Grade one candidate; the engine outcome is authoritative."""
    spec = engine_spec(contract_id)
    findings = list(form_findings(contract_id, problem, candidate))
    if findings:
        outcome: Outcome = "incorrect"
        reason = findings[0]
    else:
        try:
            request = to_correctness_request(contract_id, problem, candidate)
        except EngineAdapterGap as exc:
            outcome = "unsupported"
            reason = str(exc)
            findings.append(str(exc))
        else:
            result = check_in_process(request)
            outcome = result.outcome
            reason = result.reason
    kernel_verdict = (
        _kernel_agreement(spec, problem, candidate, findings)
        if compare_kernel
        else None
    )
    return EngineGrading(
        outcome=outcome,
        reason=reason,
        kernel_verdict=kernel_verdict,
        findings=tuple(findings),
    )


__all__ = [
    "EngineGrading",
    "KernelVerdict",
    "engine_spec",
    "grade_answer",
    "is_refusal",
]
