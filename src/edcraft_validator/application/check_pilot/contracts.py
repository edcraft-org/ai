"""Trusted check contracts, scopes and application-owned applicability.

A contract is developer-owned mathematics. A model may propose a contract id
and a structured goal, but the application decides whether that goal is inside
the contract and whether a stored check's scope covers the concrete template.
No topic label is ever translated into a capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeGuard

from edcraft_validator.application.check_pilot.kernel_registry import (
    KernelContractSpec,
    kernel_contract,
    kernel_contract_specs,
)
from edcraft_validator.application.check_pilot.models import (
    KERNEL_SCOPE_SCHEMA_VERSION,
    RECIPE_OPERATION_SET,
    SOLVE_RECIPE_OPERATION_SET,
    STRUCTURED_RECIPE_OPERATION_SET,
    ContractScope,
    GoalRelation,
    KernelContractScope,
    KernelGoal,
    PilotTemplateDefinition,
    PolynomialFamily,
    PolynomialScope,
    SolveFamily,
    StructuredGoal,
)
from edcraft_validator.application.check_pilot.structured import (
    structured_family_goal,
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
    template_min_degree: int
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
            "operation_set": self.operation_set,
            "relations": list(self.relations),
            # Planning and template authoring start at template_min_degree. The
            # stored check scope may cover lower-degree constant boundary cases.
            "min_degree": self.template_min_degree,
            "check_min_degree": self.min_degree,
            "max_degree": self.max_degree,
            "max_abs_coefficient": self.max_abs_coefficient,
            "answer_type": self.answer_type,
            "required_policy": list(self.required_policy),
        }


Contract = ContractDescriptor | KernelContractSpec
Scope = ContractScope | KernelContractScope | PolynomialScope
Goal = StructuredGoal | KernelGoal


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
        template_min_degree=1,
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
        template_min_degree=1,
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
        template_min_degree=1,
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
_CONTRACT_INDEX: dict[str, Contract] = {
    contract.contract_id: contract for contract in _CONTRACTS
}
_CONTRACT_INDEX.update({spec.contract_id: spec for spec in kernel_contract_specs()})


def contract_catalogue() -> list[dict[str, Any]]:
    """Model-facing trusted capability descriptors."""
    contracts: list[Contract] = [*_CONTRACTS, *kernel_contract_specs()]
    return [contract.descriptor() for contract in contracts]


def get_contract(contract_id: str | None) -> Contract | None:
    if not isinstance(contract_id, str):
        return None
    return _CONTRACT_INDEX.get(contract_id)


def is_kernel_contract(
    contract: Contract | None,
) -> TypeGuard[KernelContractSpec]:
    return isinstance(contract, KernelContractSpec)


def trusted_contract_scope(scope: Scope) -> Scope:
    """Return the scope only when it is exactly one trusted contract's scope."""
    if isinstance(scope, KernelContractScope):
        spec = kernel_contract(scope.contract_id)
        if spec is None or spec.scope() != scope:
            raise ValueError("recipe scope is not a trusted kernel contract scope")
        return scope
    if isinstance(scope, PolynomialScope):
        if scope.operation != "differentiate":
            raise ValueError("recipe scope is not a trusted contract scope")
        contract = get_contract(DIFFERENTIATE_CONTRACT)
    else:
        contract = get_contract(scope.contract_id)
    if (
        contract is None
        or isinstance(contract, KernelContractSpec)
        or contract.scope() != scope
    ):
        raise ValueError("recipe scope is not a trusted contract scope")
    return scope


def contract_for_scope(scope: dict[str, Any]) -> Contract | None:
    """Resolve a stored scope, including legacy v1 differentiation scopes."""
    if scope.get("schema_version") == KERNEL_SCOPE_SCHEMA_VERSION:
        try:
            kernel_scope = KernelContractScope.model_validate(scope)
        except ValueError:
            return None
        spec = kernel_contract(kernel_scope.contract_id)
        if spec is None or spec.scope() != kernel_scope:
            return None
        return spec
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


def parse_scope(scope: dict[str, Any]) -> Scope:
    """Parse one stored or proposed scope into its closed model."""
    if not isinstance(scope, dict):
        raise ValueError("stored check scope must be an object")
    if scope.get("schema_version") == KERNEL_SCOPE_SCHEMA_VERSION:
        return KernelContractScope.model_validate(scope)
    if "contract_id" in scope:
        return ContractScope.model_validate(scope)
    return PolynomialScope.model_validate(scope)


def _kernel_scope_findings(
    contract: KernelContractSpec,
    scope: KernelContractScope,
    goal: KernelGoal,
) -> list[str]:
    findings: list[str] = []
    if scope.contract_id != contract.contract_id:
        findings.append("stored check scope names a different contract")
    if scope.operation != contract.operation:
        findings.append("stored check operation does not cover the requested task")
    if scope.answer_type != contract.answer_type:
        findings.append("stored check answer type does not cover the request")
    if goal.min_degree < scope.min_degree:
        findings.append("requested minimum degree is outside the stored check scope")
    if goal.max_degree > scope.max_degree:
        findings.append("requested maximum degree is outside the stored check scope")
    if goal.max_abs_coefficient > scope.max_abs_coefficient:
        findings.append("requested coefficient bound is outside the stored check scope")
    if goal.max_dimension > scope.max_dimension:
        findings.append("requested dimension is outside the stored check scope")
    # A general-capable contract still accepts one-primitive requests: the
    # problem payload carries the requested form, so scope coverage is one-way.
    # Only a general request that the scope cannot cover is a finding.
    if (
        goal.requires_general_antiderivative
        and not scope.requires_general_antiderivative
    ):
        findings.append(
            "requested general antiderivative is outside the stored check scope"
        )
    missing = set(contract.required_policy) - set(scope.required_policy)
    if missing:
        findings.append("stored check policy omits a mandatory contract policy")
    extra = set(scope.required_policy) - set(contract.required_policy)
    if extra:
        findings.append("stored check policy is outside the trusted contract")
    if set(goal.domain_assumptions) != set(scope.domain_assumptions):
        findings.append("requested domain assumptions do not match the stored scope")
    return findings


def _scope_applicability_findings(
    contract: Contract,
    scope: Scope,
    goal: Goal,
) -> list[str]:
    findings: list[str] = []
    if isinstance(contract, KernelContractSpec):
        if not isinstance(scope, KernelContractScope) or not isinstance(
            goal, KernelGoal
        ):
            return ["kernel contracts require a kernel scope and kernel goal"]
        return _kernel_scope_findings(contract, scope, goal)
    if isinstance(goal, KernelGoal) or isinstance(scope, KernelContractScope):
        return ["the stored scope does not belong to this kernel contract"]
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


def _kernel_goal_findings(contract: KernelContractSpec, goal: KernelGoal) -> list[str]:
    findings: list[str] = []
    if goal.operation != contract.operation:
        findings.append(
            f"contract {contract.contract_id} requires operation {contract.operation}"
        )
    if goal.answer_type != contract.answer_type:
        findings.append("requested answer type is outside the contract")
    if goal.min_degree < contract.min_degree:
        findings.append("requested minimum degree is outside the contract")
    if goal.max_degree > contract.max_degree:
        findings.append("requested maximum degree is outside the contract")
    if not 1 <= goal.max_abs_coefficient <= contract.max_abs_coefficient:
        findings.append("requested coefficient bound is outside the contract")
    # A minimum below the contract floor is not a finding: the contract cannot
    # generate below its own minimum, so the floor narrows the request instead.
    if goal.min_dimension > goal.max_dimension:
        findings.append("requested minimum dimension exceeds its maximum")
    if goal.max_dimension > contract.max_dimension:
        findings.append("requested dimension is outside the contract")
    if goal.requires_general_antiderivative and contract.operation != "antiderivative":
        findings.append("only antiderivative plans can require a general answer")
    if set(goal.domain_assumptions) != set(contract.domain_assumptions):
        findings.append("requested domain assumptions do not match the contract")
    return findings


def applicability_findings(contract: Contract | None, goal: Goal) -> list[str]:
    """Validate a model-proposed goal against the trusted contract alone."""
    if contract is None:
        return ["the proposed check contract is not trusted"]
    if isinstance(contract, KernelContractSpec):
        if not isinstance(goal, KernelGoal):
            return ["kernel contracts require a kernel goal"]
        return _kernel_goal_findings(contract, goal)
    if isinstance(goal, KernelGoal):
        return ["the kernel goal does not belong to this contract"]
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
    if goal.min_degree < contract.template_min_degree:
        findings.append(
            "requested minimum degree is outside the current template authoring range"
        )
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


def scope_applicability_findings(scope: dict[str, Any], goal: Goal) -> list[str]:
    """Check that one stored check scope covers a concrete structured goal."""
    contract = contract_for_scope(scope)
    if contract is None:
        return ["stored check scope is not a trusted contract"]
    findings = applicability_findings(contract, goal)
    if findings:
        return findings
    try:
        parsed: Scope
        if scope.get("schema_version") == KERNEL_SCOPE_SCHEMA_VERSION:
            parsed = parse_scope(scope)
        elif "contract_id" in scope:
            parsed = ContractScope.model_validate(scope)
        else:
            parsed = PolynomialScope.model_validate(scope)
    except ValueError:
        return ["stored check scope is invalid"]
    return _scope_applicability_findings(contract, parsed, goal)


def template_goal(definition: PilotTemplateDefinition) -> Goal:
    """Derive the actual structured goal of a concrete template definition."""
    if definition.structured_family is not None:
        return structured_family_goal(definition.structured_family)
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


def plan_covers_template_findings(plan_goal: Goal, actual: Goal) -> list[str]:
    """A concrete template must stay inside the plan the model just described."""
    if isinstance(plan_goal, KernelGoal) or isinstance(actual, KernelGoal):
        if not isinstance(plan_goal, KernelGoal) or not isinstance(actual, KernelGoal):
            return ["template task does not match the selected plan"]
        return _kernel_plan_findings(plan_goal, actual)
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


def _kernel_plan_findings(plan: KernelGoal, actual: KernelGoal) -> list[str]:
    findings: list[str] = []
    if plan.operation != actual.operation:
        findings.append("template task does not match the selected plan")
    if plan.answer_type != actual.answer_type:
        findings.append("template answer type does not match the selected plan")
    if not plan.min_degree <= actual.min_degree:
        findings.append("template degree is below the selected plan")
    if actual.max_degree > plan.max_degree:
        findings.append("template degree is above the selected plan")
    if actual.max_abs_coefficient > plan.max_abs_coefficient:
        findings.append("template coefficient bound exceeds the selected plan")
    if not plan.min_dimension <= actual.min_dimension:
        findings.append("template dimension is below the selected plan")
    if actual.max_dimension > plan.max_dimension:
        findings.append("template dimension exceeds the selected plan")
    if plan.requires_general_antiderivative != actual.requires_general_antiderivative:
        findings.append("template antiderivative form does not match the selected plan")
    if set(plan.domain_assumptions) != set(actual.domain_assumptions):
        findings.append("template domain assumptions do not match the selected plan")
    return findings


def scope_from_recipe_operation_set(
    operation_set: str, *, contract_id: str | None = None
) -> Scope:
    """Trusted scope for standalone recipe execution.

    Differentiation defaults to the differentiation contract and solve recipes
    default to the equation contract. An inequality recipe must name its
    inequality contract explicitly; a relation outside the selected contract is
    rejected by execution rather than answered with a fabricated verdict.
    Structured recipes must name their kernel contract explicitly.
    """
    if operation_set == STRUCTURED_RECIPE_OPERATION_SET:
        if contract_id is None:
            raise ValueError("structured recipes must name their trusted contract")
        contract = get_contract(contract_id)
        if not isinstance(contract, KernelContractSpec):
            raise ValueError(
                "requested check contract is not a trusted kernel contract"
            )
        return contract.scope()
    if contract_id is None:
        contract_id = (
            EQUATION_CONTRACT
            if operation_set == SOLVE_RECIPE_OPERATION_SET
            else DIFFERENTIATE_CONTRACT
        )
    contract = get_contract(contract_id)
    if contract is None or isinstance(contract, KernelContractSpec):
        raise ValueError("requested check contract is not trusted")
    if contract.operation_set != operation_set:
        raise ValueError("check contract does not match the recipe operation set")
    return contract.scope()


__all__ = [
    "DIFFERENTIATE_CONTRACT",
    "EQUATION_CONTRACT",
    "INEQUALITY_CONTRACT",
    "Contract",
    "ContractDescriptor",
    "Goal",
    "Scope",
    "applicability_findings",
    "contract_catalogue",
    "contract_for_scope",
    "contract_id_for_scope",
    "get_contract",
    "is_kernel_contract",
    "parse_scope",
    "plan_covers_template_findings",
    "scope_applicability_findings",
    "scope_from_recipe_operation_set",
    "template_goal",
    "trusted_contract_scope",
]
