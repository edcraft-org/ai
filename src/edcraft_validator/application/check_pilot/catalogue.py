"""Owner-private check catalogue lookup, plan validation and applicability.

The model proposes a trusted contract id and a structured goal. This module is
application-owned: it resolves saved checks, validates exact references and
decides whether a check's stored scope covers a concrete goal. No request topic
string is ever translated into a capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from edcraft_validator.application.check_pilot.contracts import (
    ContractDescriptor,
    applicability_findings,
    contract_id_for_scope,
    get_contract,
    scope_applicability_findings,
)
from edcraft_validator.application.check_pilot.errors import PilotNotFound
from edcraft_validator.application.check_pilot.models import (
    CheckPlanProposal,
    CheckRecord,
    CheckRef,
    StructuredGoal,
)
from edcraft_validator.application.check_pilot.storage import PilotStore

MAX_PLANNER_CHECKS = 50
SelectionSource = Literal["saved", "authored"]


@dataclass(frozen=True, slots=True)
class PlanResolution:
    contract: ContractDescriptor | None
    goal: StructuredGoal | None
    check: CheckRecord | None
    findings: list[str]
    referenced: bool = False

    @property
    def supported(self) -> bool:
        return not self.findings


def _qualified(record: CheckRecord) -> bool:
    return record.qualification.status == "passed"


def check_descriptor(record: CheckRecord) -> dict[str, Any]:
    """A compact, model-facing descriptor for one qualified saved check."""
    return {
        "check_ref": record.check_ref.model_dump(mode="json"),
        "title": record.title,
        "contract_id": contract_id_for_scope(record.scope),
        "scope": record.scope,
        "qualification": record.qualification.status,
    }


def qualified_check_descriptors(
    records: list[CheckRecord],
) -> list[dict[str, Any]]:
    qualified = [record for record in records if _qualified(record)]
    newest = reversed(qualified[-MAX_PLANNER_CHECKS:])
    return [check_descriptor(record) for record in newest]


def find_applicable_check(
    store: PilotStore,
    owner_id: str,
    *,
    goal: StructuredGoal,
    contract_id: str,
) -> CheckRecord | None:
    """Newest qualified check whose concrete scope covers the goal."""
    for record in reversed(store.list_checks(owner_id)):
        if not _qualified(record):
            continue
        if contract_id_for_scope(record.scope) != contract_id:
            continue
        if scope_applicability_findings(record.scope, goal):
            continue
        return record
    return None


def _resolve_reference(
    store: PilotStore,
    owner_id: str,
    reference: CheckRef,
    *,
    contract: ContractDescriptor,
    goal: StructuredGoal,
) -> tuple[CheckRecord | None, list[str]]:
    try:
        record = store.get_check(owner_id, reference.check_id)
    except PilotNotFound:
        return None, [
            "the selected saved check was not found in this owner's catalogue"
        ]
    if record.check_ref != reference:
        return None, [
            "the selected saved check reference is stale or does not match the "
            "stored version and hash"
        ]
    if not _qualified(record):
        return None, ["the selected saved check is not qualified"]
    if contract_id_for_scope(record.scope) != contract.contract_id:
        return None, [
            "the selected saved check belongs to a different trusted contract"
        ]
    findings = scope_applicability_findings(record.scope, goal)
    return (record if not findings else None), findings


def resolve_plan(
    store: PilotStore,
    owner_id: str,
    proposal: CheckPlanProposal,
) -> PlanResolution:
    """Validate one structured plan; never substitute a different task."""
    if not proposal.supported:
        development = (proposal.development_needed or "").strip()
        return PlanResolution(
            contract=None,
            goal=None,
            check=None,
            findings=[f"Development needed: {development}"],
        )
    contract = get_contract(proposal.contract_id)
    goal = proposal.goal
    assert goal is not None
    findings = applicability_findings(contract, goal)
    if contract is None or findings:
        return PlanResolution(
            contract=contract,
            goal=goal,
            check=None,
            findings=findings or ["the proposed check contract is not trusted"],
        )
    if proposal.saved_check_ref is not None:
        check, reference_findings = _resolve_reference(
            store,
            owner_id,
            proposal.saved_check_ref,
            contract=contract,
            goal=goal,
        )
        return PlanResolution(
            contract=contract,
            goal=goal,
            check=check,
            findings=reference_findings,
            referenced=True,
        )
    return PlanResolution(
        contract=contract,
        goal=goal,
        check=find_applicable_check(
            store,
            owner_id,
            goal=goal,
            contract_id=contract.contract_id,
        ),
        findings=[],
        referenced=False,
    )


__all__ = [
    "MAX_PLANNER_CHECKS",
    "PlanResolution",
    "SelectionSource",
    "check_descriptor",
    "find_applicable_check",
    "qualified_check_descriptors",
    "resolve_plan",
]
