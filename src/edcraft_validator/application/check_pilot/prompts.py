"""Distinct structured prompt roles for check and template authoring."""

from __future__ import annotations

import json

from edcraft_validator.application.check_pilot.models import (
    SUPPORTED_SCOPE,
    CheckAuthorProposal,
    CheckRecord,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.operations import operation_catalogue
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

CHECK_PROMPT_VERSION = "check-author/1"
TEMPLATE_PROMPT_VERSION = "template-author/1"

CHECK_SYSTEM_PROMPT = """\
You are the check author for a private polynomial-differentiation pilot.
Propose one reusable check recipe and a short explanation. The application,
not you, owns qualification and decides whether the recipe is usable.

Trusted typed operation descriptors (ids, versions, input/output types):
{operations}

Recipe rules:
- Return one closed recipe and no code. A recipe has `steps` and `output`.
- Inputs are `problem` (a bounded univariate polynomial) and `candidate`
  (the learner's parsed polynomial answer).
- Step arguments are objects: {"source":"input","name":"problem"},
  {"source":"step","name":"d1"}, or {"source":"literal","value":true}.
- The output must be a `poly.equivalent` verdict. Its `expected` argument must
  reference a prior `poly.differentiate` step, and its `actual` argument must
  be the `candidate` input.
- Weak operations (identity, point evaluation, number equality and constant
  verdicts) are listed for completeness but are rejected. Never return them.
- Use unique step ids and only reference earlier steps. Keep at most 8 steps.
- If the request needs a different operation or a topic outside univariate real
  polynomials of degree at most 5 with bounded integer coefficients, set
  `supported` to false and explain the development needed. Never invent an
  operation id or version.
- Qualification uses independent coefficient arithmetic and sampled cases.
  Passing means only that no counterexample was found in sampled cases.
"""

TEMPLATE_SYSTEM_PROMPT = """\
You are the template author for a private polynomial-differentiation pilot.
Propose only a bounded coefficient-domain family. The application owns the
question wording, the answer, the distractors, qualification and generation.

Rules:
- Return `family` with `degree` from 1 to 5.
- `coefficients` declares exactly one domain for each exponent 0..degree.
  Every domain has 1 to 12 unique integer values from -20 to 20.
- The leading coefficient domain must not contain zero.
- Never return prose question templates, answers or distractor text.
- If the request cannot be represented by these bounded coefficient domains,
  set `supported` to false and explain the development needed.
"""


def _operations_text() -> str:
    return json.dumps(
        operation_catalogue(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def build_check_generation_request(
    prompt: str,
    *,
    feedback: dict | None = None,
) -> StructuredGenerationRequest[CheckAuthorProposal]:
    scope = SUPPORTED_SCOPE.model_dump(mode="json")
    user = (
        "Author request (preserve its meaning):\n"
        f"{prompt}\n\n"
        f"Supported scope: {json.dumps(scope, sort_keys=True)}\n"
        "Return a CheckAuthorProposal. Qualification will test correct and "
        "incorrect candidate answers, alternate valid forms and boundaries."
    )
    if feedback is not None:
        user += (
            "\n\nThe previous recipe did not pass bounded qualification. "
            "Correct it using only the trusted operations. Independent held-out "
            "cases are not shown. Bounded, sanitized feedback:\n"
            f"{json.dumps(feedback, ensure_ascii=False, sort_keys=True)[:4000]}"
        )
    return StructuredGenerationRequest(
        messages=[
            {
                "role": "system",
                "content": CHECK_SYSTEM_PROMPT.replace(
                    "{operations}", _operations_text()
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
    num_distractors: int,
) -> StructuredGenerationRequest[TemplateAuthorProposal]:
    user = (
        "Author request (preserve its meaning):\n"
        f"{prompt}\n\n"
        f"Pinned qualified check: {check.check_ref.check_id} "
        f"version {check.check_ref.version}\n"
        f"Check title: {check.title}\n"
        f"Supported scope: {json.dumps(check.scope, sort_keys=True)}\n"
        f"Required distractors: {num_distractors}\n"
        "Return a TemplateAuthorProposal with coefficient domains only."
    )
    return StructuredGenerationRequest(
        messages=[
            {"role": "system", "content": TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        response_model=TemplateAuthorProposal,
        prompt_version=TEMPLATE_PROMPT_VERSION,
        schema_name="polynomial_family",
    )


__all__ = [
    "CHECK_PROMPT_VERSION",
    "CHECK_SYSTEM_PROMPT",
    "TEMPLATE_PROMPT_VERSION",
    "TEMPLATE_SYSTEM_PROMPT",
    "build_check_generation_request",
    "build_template_generation_request",
]
