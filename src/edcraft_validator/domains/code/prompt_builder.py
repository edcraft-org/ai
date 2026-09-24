"""Build code-domain prompts and the structured LLM request."""

from __future__ import annotations

import json

from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.profiles import code_template_profile
from edcraft_validator.domains.code.proposal_response import CodeProposalResponse
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

CODE_TEMPLATE_PROMPT_VERSION = "code-template-v8"


def build_template_prompt(request: CodeTemplateRequest) -> str:
    profile = code_template_profile(request.topic, request.difficulty)
    candidate_count = request.num_distractors
    shapes = [
        {
            "kinds": list(shape.kinds),
            "names": list(shape.names) if shape.names is not None else None,
        }
        for shape in profile.parameter_shapes
    ]
    contract = json.dumps(
        {
            "topic": profile.topic,
            "difficulty": profile.difficulty,
            "answer_target": profile.answer_target,
            "answer_kind": profile.answer_kind,
            "accepted_parameter_shapes": shapes,
            "required_code_features": sorted(profile.required_features),
            "positive_integer_values_required": profile.require_positive_integers,
            "required_parameter_values": profile.required_parameter_values,
            "authoring_requirements": profile.guidance,
        },
        indent=2,
        sort_keys=True,
    )
    prompt = (
        "Follow this exact capability contract. Choose exactly one accepted parameter "
        "shape. A null names value means choose valid names but preserve the exact "
        "number, order, and kinds. Do not add parameters.\n"
        f"{contract}\n"
        f"Use answer_target={profile.answer_target}. "
        f"Create exactly {candidate_count} distractor candidates; the local validator "
        f"will select {request.num_distractors}. Every candidate should model a real "
        "misconception and should differ from the answer and other candidates for the "
        "complete Cartesian product. The local application adds mechanical fallback "
        "candidates; do not add generic answer-plus-constant fallbacks yourself. In "
        "reason_template, use only plain placeholders such as "
        "`{n}`; never put expressions such as `{n-1}` inside braces. "
        "Keep the complete Cartesian product valid."
    )
    return prompt


CODE_TEMPLATE_SYSTEM_PROMPT = """\
Generate the judgment-bearing fields for one reusable Python execution-trace MCQ
template, not one concrete question. The local application derives identity, topic,
difficulty, answer target, question wording, version, and question type.

The proposal must use a finite Cartesian product of typed finite parameter values so
the local application can exhaustively validate every possible question once.

Rules:
- `code` is the learner-facing Python program that the question asks about. It must
  directly perform the selected topic's computation or control flow. Never write a
  question generator, template generator, metadata dictionary, schema, or code that
  stores answer/distractor expressions as strings. Keep code, answer_expression, and
  distractor candidates as separate schema fields.
- Define one module-level entry function whose positional arguments exactly match the
  parameter names and order. Use every parameter in executed learner-facing behavior.
  Helper functions are allowed. The code must work for every parameter combination.
- Use only expressions, assignments, if statements, and for loops. Do not use imports,
  attributes, classes, decorators, recursion, comprehensions, while loops, lambdas,
  exceptions, file access, networking, input, eval, or exec.
- Every parameter declares a kind and two to four distinct finite values. Supported
  kinds are integer (-100 through 100), boolean, string (non-empty short printable
  text), and
  integer_list (at most eight integers from -100 through 100). Encode parameter
  values according to the response schema and the user prompt's format guidance.
- The user prompt states the selected answer target. answer_expression must calculate
  that target using parameter names,
  numeric constants, arithmetic, comparisons, boolean operators, or a conditional
  expression. String constants, list literals, indexing, and the one-argument functions
  len, sum, min, max, sorted, all, and any are also supported. Do not use methods or
  other function calls.
- Each distractor candidate must represent a specific misconception. The local
  validator selects candidates that are unique, type-compatible, and different from
  the answer for every parameter combination. The local application adds mechanical
  fallback candidates after the provider response.
- reason_template explains its misconception and may use only a bare parameter
  placeholder such as `{n}`. Do not place arithmetic or any other expression inside
  braces.
- Return only the proposal schema fields and no markdown. Do not add locally derived
  fields.
"""


RESPONSE_GUIDANCE = """\
Use native JSON values matching each parameter's `kind`: integers use JSON numbers;
booleans use JSON booleans; strings use JSON strings; integer_list values use nested
JSON arrays of numbers. Do not encode numbers, booleans, or arrays as strings.
"""


def build_code_generation_request(
    request: CodeTemplateRequest,
) -> StructuredGenerationRequest[CodeProposalResponse]:
    """Return the provider-independent code proposal contract."""
    system_message = {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT}
    user_prompt = build_template_prompt(request)

    return StructuredGenerationRequest(
        messages=[
            system_message,
            {
                "role": "user",
                "content": f"{user_prompt}\n{RESPONSE_GUIDANCE}",
            },
        ],
        response_model=CodeProposalResponse,
        prompt_version=f"{CODE_TEMPLATE_PROMPT_VERSION}+response-v2",
    )
