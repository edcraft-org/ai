"""Distinct structured prompt roles for planning, checks and templates."""

from __future__ import annotations

import json

from edcraft_validator.application.check_pilot.contracts import (
    ContractDescriptor,
    contract_catalogue,
)
from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    CheckPlanProposal,
    CheckRecord,
    StructuredGoal,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.operations import operation_catalogue
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
- The goal names the operation, relation, exact degree bounds, coefficient
  bound, real domain and answer type. A solve goal must require the complete
  real solution set; root substitution or a partial set is not sufficient.
- You may return an exact `saved_check_ref` from the owner's catalogue above.
  Reference only the check id, version and sha256 you see. The application
  rejects unknown, foreign, stale or incompatible references.
- If you omit the reference, the application may reuse an applicable qualified
  check or author one. Never silently change the requested task.
- If the request needs a different operation or a topic outside these trusted
  contracts, set `supported` to false and explain the development needed.
- Do not return code, recipes or coefficient families in this planning step.
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
- Inputs are `problem` and `candidate`. For differentiation `problem` is a
  bounded polynomial and `candidate` is a parsed polynomial. For solving,
  `problem` is a bounded polynomial relation and `candidate` is a complete
  structured real solution set.
- Step arguments are objects: {{"source":"input","name":"problem"}},
  {{"source":"step","name":"d1"}}, or {{"source":"literal","value":true}}.
- Differentiation output: the `out` step must be `poly.equivalent`, whose
  `expected` argument references a prior `poly.differentiate` step and whose
  `actual` argument is the `candidate` input.
- Solve output: the `out` step must be `set.equal`, whose `expected` argument
  references a prior `relation.solve_real` step and whose `actual` argument is
  the `candidate` input. Comparing a root substitution or a partial set is
  rejected.
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
- For a differentiation contract, return `family` and no `solve_family`.
  `family` declares a degree from 1 to 5 and exactly one coefficient domain for
  each exponent 0..degree. Domains have 1 to 12 unique integer values from -20
  to 20. The leading coefficient domain must not contain zero.
- For a solve contract, return `solve_family` and no `family`. It declares a
  degree from 1 to 2, exactly one coefficient domain for each exponent
  0..degree, and the relation from the selected goal. The leading coefficient
  domain must not contain zero.
- Preserve the request's operation, relation, real domain and complete-solution
  requirement. Never return prose question templates, answers or distractor
  text.
- If the request cannot be represented by these bounded domains, set
  `supported` to false and explain the development needed.
"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _planner_checks_text(checks: list[dict] | None) -> str:
    return _json(checks or []) if checks else "[]"


def _operation_text(contract: ContractDescriptor) -> str:
    return _json(operation_catalogue(contract.operation_set))


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
    contract: ContractDescriptor,
    goal: StructuredGoal,
    feedback: dict | None = None,
) -> StructuredGenerationRequest[CheckAuthorProposal]:
    user = (
        "Author request (preserve its meaning):\n"
        f"{prompt}\n\n"
        f"Selected contract: {_json(contract.descriptor())}\n"
        f"Structured goal: {_json(goal.model_dump(mode='json'))}\n"
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
                    goal=_json(goal.model_dump(mode="json")),
                    operations=_operation_text(contract),
                    operation_set=contract.operation_set,
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
    contract: ContractDescriptor,
    goal: StructuredGoal,
    num_distractors: int,
    feedback: dict | None = None,
) -> StructuredGenerationRequest[TemplateAuthorProposal]:
    user = (
        "Author request (preserve its meaning):\n"
        f"{prompt}\n\n"
        f"Pinned qualified check: {check.check_ref.check_id} "
        f"version {check.check_ref.version} sha256 {check.check_ref.sha256}\n"
        f"Selected contract: {_json(contract.descriptor())}\n"
        f"Structured goal: {_json(goal.model_dump(mode='json'))}\n"
        f"Required distractors: {num_distractors}\n"
        "Return a TemplateAuthorProposal with structured coefficient domains only."
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
                    goal=_json(goal.model_dump(mode="json")),
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
