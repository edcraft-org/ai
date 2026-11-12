"""Trusted check contracts, scopes and application-owned applicability.

A contract is developer-owned mathematics. A model may propose a contract id
and a structured goal, but the application decides whether that goal is inside
the contract and whether a stored check's scope covers the concrete template.
No topic label is ever translated into a capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edcraft_validator.application.check_pilot.models import (
    RECIPE_OPERATION_SET,
    SOLVE_RECIPE_OPERATION_SET,
    ContractScope,
    GoalRelation,
    PilotTemplateDefinition,
    PolynomialFamily,
    PolynomialScope,
    SolveFamily,
    StructuredGoal,
)

DIFFERENTIATE_CONTRACT = "polynomial.differentiate/1"
EQUATION_CONTRACT = "polynomial.equation-real/1"
INEQUALITY_CONTRACT = "polynomial.inequality-real/1"

_INEQUALITY_RELATIONS: tuple[GoalRelation, ...] = ("lt", "le", "gt", "ge")


@dataclass(frozen=True, slots=True)
class ContractDescriptor:
    """One developer-owned capability advertised to the planning role."""

    contract_id: str
    title: str
    summary: str
    operation: str
    operation_set: str
    relations: tuple[GoalRelation, ...]
    min_degree: int
    max_degree: int
    max_abs_coefficient: int
    answer_type: str
    required_policy: tuple[str, ...]

    def scope(self) -> ContractScope:
        return ContractScope(
            contract_id=self.contract_id,
            operation=self.operation,  # type: ignore[arg-type]
            relations=list(self.relations),
            min_degree=self.min_degree,
            max_degree=self.max_degree,
            max_abs_coefficient=self.max_abs_coefficient,
            answer_type=self.answer_type,  # type: ignore[arg-type]
            required_policy=list(self.required_policy),  # type: ignore[arg-type]
        )

    def descriptor(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "title": self.title,
            "summary": self.summary,
            "operation": self.operation,
            "relations": list(self.relations),
            "min_degree": self.min_degree,
            "max_degree": self.max_degree,
            "max_abs_coefficient": self.max_abs_coefficient,
            "answer_type": self.answer_type,
            "required_policy": list(self.required_policy),
        }


_CONTRACTS: tuple[ContractDescriptor, ...] = (
    ContractDescriptor(
        contract_id=DIFFERENTIATE_CONTRACT,
        title="Differentiate a bounded univariate polynomial",
        summary=(
            "Compare the complete candidate derivative with an independently "
            "derived polynomial over all coefficients."
        ),
        operation="differentiate",
        operation_set=RECIPE_OPERATION_SET,
        relations=("none",),
        min_degree=1,
        max_degree=5,
        max_abs_coefficient=20,
        answer_type="expression",
        required_policy=(
            "complete_correctness",
            "independent_correctness",
            "all_options_checked",
        ),
    ),
    ContractDescriptor(
        contract_id=EQUATION_CONTRACT,
        title="Solve a bounded real polynomial equation",
        summary=(
            "Compute and compare the complete real solution set of a linear or "
            "quadratic equation, including repeated and non-real roots."
        ),
        operation="solve",
        operation_set=SOLVE_RECIPE_OPERATION_SET,
        relations=("eq",),
        min_degree=0,
        max_degree=2,
        max_abs_coefficient=20,
        answer_type="solution_set",
        required_policy=(
            "complete_correctness",
            "complete_real_solution_set",
            "independent_correctness",
            "all_options_checked",
        ),
    ),
    ContractDescriptor(
        contract_id=INEQUALITY_CONTRACT,
        title="Solve a bounded real polynomial inequality",
        summary=(
            "Compute and compare the complete real solution set of a linear or "
            "quadratic inequality, including interval unions and end flags."
        ),
        operation="solve",
        operation_set=SOLVE_RECIPE_OPERATION_SET,
        relations=_INEQUALITY_RELATIONS,
        min_degree=0,
        max_degree=2,
        max_abs_coefficient=20,
        answer_type="solution_set",
        required_policy=(
            "complete_correctness",
            "complete_real_solution_set",
            "independent_correctness",
            "all_options_checked",
        ),
    ),
)
_CONTRACT_INDEX = {contract.contract_id: contract for contract in _CONTRACTS}


def contract_catalogue() -> list[dict[str, Any]]:
    """Model-facing trusted capability descriptors."""
    return [contract.descriptor() for contract in _CONTRACTS]


def get_contract(contract_id: str | None) -> ContractDescriptor | None:
    if not isinstance(contract_id, str):
        return None
    return _CONTRACT_INDEX.get(contract_id)


def contract_for_scope(scope: dict[str, Any]) -> ContractDescriptor | None:
    """Resolve a stored scope, including legacy v1 differentiation scopes."""
    contract_id = scope.get("contract_id")
    if isinstance(contract_id, str):
        return get_contract(contract_id)
    try:
        legacy = PolynomialScope.model_validate(scope)
    except ValueError:
        return None
    if legacy.operation == "differentiate":
        return get_contract(DIFFERENTIATE_CONTRACT)
    return None


def contract_id_for_scope(scope: dict[str, Any]) -> str | None:
    contract = contract_for_scope(scope)
    return contract.contract_id if contract is not None else None


def _scope_for_contract(contract: ContractDescriptor) -> ContractScope:
    return contract.scope()


def _scope_relations(scope: ContractScope | PolynomialScope) -> tuple[str, ...]:
    if isinstance(scope, ContractScope):
        return tuple(scope.relations)
    return ("none",)


def _scope_applicability_findings(
    contract: ContractDescriptor,
    scope: ContractScope | PolynomialScope,
    goal: StructuredGoal,
) -> list[str]:
    findings: list[str] = []
    if isinstance(scope, ContractScope):
        if scope.contract_id != contract.contract_id:
            findings.append("stored check scope names a different contract")
        if scope.operation != goal.operation:
            findings.append("stored check operation does not cover the requested task")
        if scope.answer_type != goal.answer_type:
            findings.append("stored check answer type does not cover the request")
        if goal.relation not in scope.relations:
            findings.append("stored check relation set does not cover the request")
        if not scope.min_degree <= goal.min_degree:
            findings.append("stored check minimum degree does not cover the request")
        if goal.max_degree > scope.max_degree:
            findings.append("stored check maximum degree does not cover the request")
        if goal.max_abs_coefficient > scope.max_abs_coefficient:
            findings.append("stored check coefficient bound does not cover the request")
        missing = set(contract.required_policy) - set(scope.required_policy)
        if missing:
            findings.append(
                "stored check policy omits a mandatory trusted contract policy"
            )
        extra = set(scope.required_policy) - set(contract.required_policy)
        if extra:
            findings.append("stored check policy is outside the trusted contract")
        return findings
    # Legacy v1 differentiation scope: readable and usable, but it cannot be
    # widened into an equation or inequality check.
    if goal.operation != "differentiate" or contract.operation != "differentiate":
        findings.append("legacy differentiation scope cannot cover this task")
        return findings
    if goal.relation != "none" or goal.answer_type != "expression":
        findings.append("legacy differentiation scope requires a derivative task")
    if scope.max_degree < goal.max_degree:
        findings.append("stored check maximum degree does not cover the request")
    if scope.max_abs_coefficient < goal.max_abs_coefficient:
        findings.append("stored check coefficient bound does not cover the request")
    return findings


def applicability_findings(
    contract: ContractDescriptor | None, goal: StructuredGoal
) -> list[str]:
    """Validate a model-proposed goal against the trusted contract alone."""
    if contract is None:
        return ["the proposed check contract is not trusted"]
    findings: list[str] = []
    if goal.subject != "univariate-real-polynomial" or goal.domain != "real":
        findings.append("only bounded real univariate polynomial tasks are supported")
    if goal.operation != contract.operation:
        findings.append(
            f"contract {contract.contract_id} requires operation {contract.operation}"
        )
    if goal.relation not in contract.relations:
        findings.append(
            f"contract {contract.contract_id} does not support relation "
            f"{goal.relation!r}"
        )
    if goal.min_degree < contract.min_degree:
        findings.append("requested minimum degree is outside the contract")
    if goal.max_degree > contract.max_degree:
        findings.append("requested maximum degree is outside the contract")
    if goal.max_abs_coefficient > contract.max_abs_coefficient:
        findings.append("requested coefficient bound is outside the contract")
    if goal.answer_type != contract.answer_type:
        findings.append("requested answer type is outside the contract")
    if contract.operation == "solve" and not goal.requires_complete_solution_set:
        findings.append(
            "solve plans must require the complete real solution set; root "
            "substitution or a partial set is not sufficient"
        )
    return findings


def scope_applicability_findings(
    scope: dict[str, Any], goal: StructuredGoal
) -> list[str]:
    """Check that one stored check scope covers a concrete structured goal."""
    contract = contract_for_scope(scope)
    if contract is None:
        return ["stored check scope is not a trusted contract"]
    findings = applicability_findings(contract, goal)
    if findings:
        return findings
    try:
        parsed: ContractScope | PolynomialScope
        if "contract_id" in scope:
            parsed = ContractScope.model_validate(scope)
        else:
            parsed = PolynomialScope.model_validate(scope)
    except ValueError:
        return ["stored check scope is invalid"]
    return _scope_applicability_findings(contract, parsed, goal)


def template_goal(definition: PilotTemplateDefinition) -> StructuredGoal:
    """Derive the actual structured goal of a concrete template definition."""
    if definition.solve_family is not None:
        solve_family = definition.solve_family
        return StructuredGoal(
            operation="solve",
            relation=solve_family.relation,
            min_degree=solve_family.degree,
            max_degree=solve_family.degree,
            max_abs_coefficient=_family_bound(solve_family),
            answer_type="solution_set",
            requires_complete_solution_set=True,
        )
    polynomial_family = definition.family
    assert polynomial_family is not None
    return StructuredGoal(
        operation="differentiate",
        relation="none",
        min_degree=polynomial_family.degree,
        max_degree=polynomial_family.degree,
        max_abs_coefficient=_family_bound(polynomial_family),
        answer_type="expression",
    )


def _family_bound(family: PolynomialFamily | SolveFamily) -> int:
    return max(
        (abs(value) for domain in family.coefficients for value in domain.values),
        default=1,
    )


def plan_covers_template_findings(
    plan_goal: StructuredGoal, actual: StructuredGoal
) -> list[str]:
    """A concrete template must stay inside the plan the model just described."""
    findings: list[str] = []
    if plan_goal.operation != actual.operation:
        findings.append("template task does not match the selected plan")
    if plan_goal.relation != actual.relation:
        findings.append("template relation does not match the selected plan")
    if not plan_goal.min_degree <= actual.min_degree:
        findings.append("template degree is below the selected plan")
    if actual.max_degree > plan_goal.max_degree:
        findings.append("template degree is above the selected plan")
    if actual.max_abs_coefficient > plan_goal.max_abs_coefficient:
        findings.append("template coefficient bound exceeds the selected plan")
    if plan_goal.answer_type != actual.answer_type:
        findings.append("template answer type does not match the selected plan")
    if (
        plan_goal.requires_complete_solution_set
        and not actual.requires_complete_solution_set
    ):
        findings.append("template does not require the complete solution set")
    return findings


def scope_from_recipe_operation_set(operation_set: str) -> ContractScope:
    """Default scope for a standalone recipe invoked through the MCP adapter."""
    if operation_set == SOLVE_RECIPE_OPERATION_SET:
        return ContractScope(
            contract_id=EQUATION_CONTRACT,
            operation="solve",
            relations=["eq", "lt", "le", "gt", "ge"],
            min_degree=0,
            max_degree=2,
            max_abs_coefficient=20,
            answer_type="solution_set",
            required_policy=[
                "complete_correctness",
                "complete_real_solution_set",
                "independent_correctness",
                "all_options_checked",
            ],
        )
    contract = get_contract(DIFFERENTIATE_CONTRACT)
    assert contract is not None
    return contract.scope()


__all__ = [
    "DIFFERENTIATE_CONTRACT",
    "EQUATION_CONTRACT",
    "INEQUALITY_CONTRACT",
    "ContractDescriptor",
    "applicability_findings",
    "contract_catalogue",
    "contract_for_scope",
    "contract_id_for_scope",
    "get_contract",
    "plan_covers_template_findings",
    "scope_applicability_findings",
    "scope_from_recipe_operation_set",
    "template_goal",
]
