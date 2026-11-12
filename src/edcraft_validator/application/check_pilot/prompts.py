"""Distinct structured prompt roles for planning, checks and templates."""

from __future__ import annotations

import json

from edcraft_validator.application.check_pilot.contracts import (
    Contract,
    Goal,
    contract_catalogue,
    is_kernel_contract,
)
from edcraft_validator.application.check_pilot.kernel_registry import (
    KernelContractSpec,
    kernel_boundary_problems,
)
from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    CheckPlanProposal,
    CheckRecord,
    KernelGoal,
    NumericBinding,
    StructuredProblemFamily,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.operations import operation_catalogue
from edcraft_validator.application.check_pilot.structured import (
    numeric_leaf_paths,
    validate_structured_family,
)
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

PLANNER_PROMPT_VERSION = "check-planner/1"
CHECK_PROMPT_VERSION = "check-author/2"
TEMPLATE_PROMPT_VERSION = "template-author/2"

PLANNER_SYSTEM_PROMPT = """\
You are the planning role for a private catalogue of reusable mathematics
checks. You describe the mathematical task and select exactly one trusted
contract; the application, not you, decides whether anything is applicable.

Trusted contracts:
{contracts}

The owner's qualified saved checks:
{checks}

Rules:
- For a supported request, return a trusted `contract_id`, a structured `goal`
  and a short `reason`.
- Polynomial contracts use `operation`, `relation`, exact degree bounds,
  coefficient bound, real domain and answer type. A solve goal must require the
  complete real solution set; root substitution or a partial set is not
  sufficient.
- Kernel contracts use `operation`, `answer_type`, `min_degree`, `max_degree`,
  `max_abs_coefficient`, `max_dimension`, `requires_general_antiderivative` and
  the contract's exact `domain_assumptions`. Use the bounds and assumptions in
  the catalogue above; do not widen them.
- A valid kernel goal example:
{goal_example}
- You may return an exact `saved_check_ref` from the owner's catalogue above.
  Reference only the check id, version and sha256 you see. The application
  rejects unknown, foreign, stale or incompatible references.
- If you omit the reference, the application may reuse an applicable qualified
  check or author one. Never silently change the requested task.
- If the request needs a different operation or a topic outside these trusted
  contracts, set `supported` to false and explain the development needed.
- Do not return code, recipes or problem families in this planning step.
"""

CHECK_SYSTEM_PROMPT = """\
You are the check author for a private reusable-mathematics catalogue.
Compose one closed check recipe for the selected trusted contract. The
application, not you, owns qualification and decides whether it is usable.

Selected contract:
{contract}

Structured goal:
{goal}

Trusted typed operation descriptors for this contract:
{operations}

Recipe rules:
- Return one closed recipe and no code. The recipe's `operation_set` must be
  `{operation_set}`.
- Inputs are `problem` and `candidate`. Their Python-side types depend on the
  operation set; never invent an input type or operation.
- Each step must name exactly one registered operation and version, and its
  `arguments` must contain exactly that operation's input names. Never add
  unused argument names or nullable placeholder keys for other operations.
- Input and step arguments are written with a name and a JSON null value:
  {{"source":"input","name":"problem","value":null}},
  {{"source":"step","name":"d1","value":null}}.
- Literal arguments have a null name and a non-null integer, boolean or string
  value: {{"source":"literal","name":null,"value":true}}. Literals never carry
  a name.
- {output_rule}
- Use unique step ids and only reference earlier steps. Keep at most 8 steps.
- Weak operations are listed for completeness but are rejected.
- If the request cannot be represented, set `supported` to false and explain
  the development needed. Never invent an operation id or version.
- Qualification uses independent sampled cases. Passing means only that no
  counterexample was found in sampled cases.
"""

TEMPLATE_SYSTEM_PROMPT = """\
You are the template author for a private reusable-mathematics catalogue.
Propose only structured data for the selected trusted contract. The application
owns question wording, answers, options, qualification and generation.

Selected contract:
{contract}

Structured goal:
{goal}

Rules:
- Return `contract_id` equal to the selected contract id.
- {family_rule}
- Bindings are exact parameter domains, not a question pattern: `path` addresses
  one genuine numeric leaf in the problem (never `kind`, `sym`, `op`, `variable`
  or other metadata), and `values` are 1 to 12 distinct integers within the
  contract bounds. The application samples these directly; you may vary
  exponents only when every bound instance stays inside the contract.
- Preserve the request's operation, answer type, real domain and complete-set or
  general-antiderivative requirement. Never return prose question templates,
  answers or distractor text.
- If the request cannot be represented by these bounded domains, set
  `supported` to false and explain the development needed.
"""

_KERNEL_OUTPUT_RULE = (
    "Kernel output: the `out` step must be `structured.accepts`, whose "
    "`expected` argument references a prior `structured.expected` step, whose "
    "`problem` argument is the `problem` input, and whose `candidate` argument "
    "is the `candidate` input. The oracle and checker must remain separate "
    "operations."
)
_LEGACY_OUTPUT_RULES = {
    "differentiate": (
        "Differentiation output: the `out` step must be `poly.equivalent`, whose "
        "`expected` argument references a prior `poly.differentiate` step and "
        "whose `actual` argument is the `candidate` input."
    ),
    "solve": (
        "Solve output: the `out` step must be `set.equal`, whose `expected` "
        "argument references a prior `relation.solve_real` step and whose "
        "`actual` argument is the `candidate` input. Comparing a root "
        "substitution or a partial set is rejected."
    ),
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _planner_checks_text(checks: list[dict] | None) -> str:
    return _json(checks or []) if checks else "[]"


def _operation_text(contract: Contract) -> str:
    return _json(operation_catalogue(contract.operation_set))


def _goal_text(goal: Goal) -> str:
    return _json(goal.model_dump(mode="json"))


def _kernel_goal_example() -> str:
    spec = next(
        (
            contract
            for contract in contract_catalogue()
            if contract["contract_id"] == "matrix.determinant/1"
        ),
        None,
    )
    if spec is None:
        return "{}"
    goal = KernelGoal(
        operation=spec["operation"],
        answer_type=spec["answer_type"],
        min_degree=spec["min_degree"],
        max_degree=spec["max_degree"],
        max_abs_coefficient=spec["max_abs_coefficient"],
        max_dimension=spec["max_dimension"],
        requires_general_antiderivative=False,
        domain_assumptions=list(spec["domain_assumptions"]),
    )
    return _json(goal.model_dump(mode="json"))


def _kernel_family_example(contract: KernelContractSpec) -> str:
    for problem in kernel_boundary_problems(contract.contract_id):
        paths = numeric_leaf_paths(problem)
        for path in paths:
            values = [-2, -1, 1, 2]
            try:
                family = StructuredProblemFamily(
                    contract_id=contract.contract_id,
                    problem=problem,
                    bindings=[NumericBinding(path=path, values=values)],
                    num_distractors=3,
                )
            except ValueError:
                continue
            try:
                validate_structured_family(family)
            except ValueError:
                continue
            return _json(family.model_dump(mode="json"))
    fallback = StructuredProblemFamily(
        contract_id=contract.contract_id,
        problem=kernel_boundary_problems(contract.contract_id)[0],
        bindings=[],
        num_distractors=3,
    )
    return _json(fallback.model_dump(mode="json"))


def _output_rule(contract: Contract) -> str:
    if is_kernel_contract(contract):
        return _KERNEL_OUTPUT_RULE
    return _LEGACY_OUTPUT_RULES.get(contract.operation, _LEGACY_OUTPUT_RULES["solve"])


def _family_rule(contract: Contract) -> str:
    if is_kernel_contract(contract):
        return (
            "For a kernel contract, return `structured_family` and no `family` "
            "or `solve_family`. Its `problem` must be exactly one closed problem "
            "variant advertised in the response schema, and its `bindings` name "
            "numeric parameter domains in that problem. A valid example for this "
            "contract is:\n"
            f"{_kernel_family_example(contract)}"
        )
    if contract.operation == "differentiate":
        return (
            "For a differentiation contract, return `family` and no "
            "`solve_family` or `structured_family`. `family` declares a degree "
            "from 1 to 5 and exactly one coefficient domain for each exponent "
            "0..degree. Domains have 1 to 12 unique integer values from -20 to "
            "20. The leading coefficient domain must not contain zero."
        )
    return (
        "For a solve contract, return `solve_family` and no `family` or "
        "`structured_family`. It declares a degree from 1 to 2, exactly one "
        "coefficient domain for each exponent 0..degree, and the relation from "
        "the selected goal. The leading coefficient domain must not contain zero."
    )


def build_plan_generation_request(
    prompt: str,
    *,
    checks: list[dict] | None = None,
    feedback: dict | None = None,
) -> StructuredGenerationRequest[CheckPlanProposal]:
    user = (
        "Teaching request (preserve its meaning):\n"
        f"{prompt}\n\n"
        "Return a CheckPlanProposal. The application validates the contract, "
        "goal and any saved reference before using them."
    )
    if feedback is not None:
        user += (
            "\n\nThe previous plan was rejected by application-owned validation. "
            "Correct it using only trusted contracts and exact saved references. "
            "Bounded feedback:\n"
            f"{_json(feedback)[:4000]}"
        )
    return StructuredGenerationRequest(
        messages=[
            {
                "role": "system",
                "content": PLANNER_SYSTEM_PROMPT.format(
                    contracts=_json(contract_catalogue()),
                    checks=_planner_checks_text(checks),
                    goal_example=_kernel_goal_example(),
                ),
            },
            {"role": "user", "content": user},
        ],
        response_model=CheckPlanProposal,
        prompt_version=PLANNER_PROMPT_VERSION,
        schema_name="check_plan",
    )


def build_check_generation_request(
    prompt: str,
    *,
    contract: Contract,
    goal: Goal,
    feedback: dict | None = None,
) -> StructuredGenerationRequest[CheckAuthorProposal]:
    user = (
        "Author request (preserve its meaning):\n"
        f"{prompt}\n\n"
        f"Selected contract: {_json(contract.descriptor())}\n"
        f"Structured goal: {_goal_text(goal)}\n"
        "Return a CheckAuthorProposal. Qualification will test correct and "
        "incorrect candidate answers, boundaries and non-vacuous mutations."
    )
    if feedback is not None:
        user += (
            "\n\nThe previous recipe did not pass bounded qualification. "
            "Correct it using only the trusted operations for this contract. "
            "Independent held-out cases are not shown. Bounded, sanitized "
            "feedback:\n"
            f"{_json(feedback)[:4000]}"
        )
    return StructuredGenerationRequest(
        messages=[
            {
                "role": "system",
                "content": CHECK_SYSTEM_PROMPT.format(
                    contract=_json(contract.descriptor()),
                    goal=_goal_text(goal),
                    operations=_operation_text(contract),
                    operation_set=contract.operation_set,
                    output_rule=_output_rule(contract),
                ),
            },
            {"role": "user", "content": user},
        ],
        response_model=CheckAuthorProposal,
        prompt_version=CHECK_PROMPT_VERSION,
        schema_name="check_recipe",
    )


def build_template_generation_request(
    prompt: str,
    *,
    check: CheckRecord,
    contract: Contract,
    goal: Goal,
    num_distractors: int,
    feedback: dict | None = None,
) -> StructuredGenerationRequest[TemplateAuthorProposal]:
    user = (
        "Author request (preserve its meaning):\n"
        f"{prompt}\n\n"
        f"Pinned qualified check: {check.check_ref.check_id} "
        f"version {check.check_ref.version} sha256 {check.check_ref.sha256}\n"
        f"Selected contract: {_json(contract.descriptor())}\n"
        f"Structured goal: {_goal_text(goal)}\n"
        f"Required distractors: {num_distractors}\n"
        "Return a TemplateAuthorProposal with one structured family only."
    )
    if feedback is not None:
        user += (
            "\n\nThe previous template proposal did not preserve the selected "
            "contract or goal. Correct it. Bounded feedback:\n"
            f"{_json(feedback)[:4000]}"
        )
    return StructuredGenerationRequest(
        messages=[
            {
                "role": "system",
                "content": TEMPLATE_SYSTEM_PROMPT.format(
                    contract=_json(contract.descriptor()),
                    goal=_goal_text(goal),
                    family_rule=_family_rule(contract),
                ),
            },
            {"role": "user", "content": user},
        ],
        response_model=TemplateAuthorProposal,
        prompt_version=TEMPLATE_PROMPT_VERSION,
        schema_name="polynomial_family",
    )


__all__ = [
    "CHECK_PROMPT_VERSION",
    "CHECK_SYSTEM_PROMPT",
    "PLANNER_PROMPT_VERSION",
    "PLANNER_SYSTEM_PROMPT",
    "TEMPLATE_PROMPT_VERSION",
    "TEMPLATE_SYSTEM_PROMPT",
    "build_check_generation_request",
    "build_plan_generation_request",
    "build_template_generation_request",
]
