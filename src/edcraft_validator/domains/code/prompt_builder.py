"""Build code-domain prompts and the structured LLM request."""

from __future__ import annotations

from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.proposal_response import CodeProposalResponse
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)

CODE_TEMPLATE_PROMPT_VERSION = "code-template-v10"

CODE_RECOMMENDED_CHECK_NAMES = (
    "template_structure",
    "expression_safety",
    "answer_domain",
    "code_execution",
    "canonical_answers",
    "distractor_selection",
    "distractor_consistency",
    "template_rendering",
)


def build_template_prompt(
    request: CodeTemplateRequest,
    *,
    offered_tool_names: tuple[str, ...] = CODE_RECOMMENDED_CHECK_NAMES,
) -> str:
    offered = ", ".join(offered_tool_names)
    return f"""\
Author request (preserve its meaning; do not replace it with a catalogue topic):
{request.prompt}

Requested difficulty: {request.difficulty}
Required usable distractors: {request.num_distractors}
Checks available for recommendation: {offered}

Choose the entry function, finite parameters, learner-facing question template, and
one supported answer_target. The question_template must name the entry function and
use every parameter exactly as a plain placeholder such as `{{n}}`. Its wording must
unambiguously ask for the selected answer_target. The exact entry_function identifier
must appear verbatim in question_template as a function call. For example, if
entry_function is `calculate_expression`, write `What does
calculate_expression({{a}}, {{b}}, {{c}}) return?`; do not replace the call with a
description of the arithmetic expression.

Return at least {request.num_distractors} distractor candidates that model real
misconceptions and remain type-compatible, distinct from the answer, and mutually
distinct for the complete Cartesian product. In reason_template, use only plain
parameter placeholders such as `{{n}}`; never put expressions inside braces.

Recommend a nonempty fixed subset of the available checks. Use each check name at
most once, do not invent names, and return an empty `arguments` object for every
check. The current application still runs its complete validation pipeline; this
recommendation is recorded for the later tool workflow.
"""


CODE_TEMPLATE_SYSTEM_PROMPT = """\
Generate one complete reusable Python execution-trace MCQ proposal and recommend its
fixed validation checks in the same structured response. Do not generate one concrete
question. The local application derives identity, difficulty, version, and question
type; you author the question template, code, entry function, answer target, answer
expression, finite parameters, and distractors.

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
- Select exactly one supported answer_target: return_value, loop_iterations,
  loop_executions, branch_executions, or function_calls. answer_expression must
  calculate that target using parameter names,
  numeric constants, arithmetic, comparisons, boolean operators, or a conditional
  expression. String constants, list literals, indexing, and the one-argument functions
  len, sum, min, max, sorted, all, and any are also supported. Do not use methods or
  other function calls.
- question_template must name the entry function and use plain placeholders for every
  declared parameter. Its wording must match answer_target.
- Each distractor candidate must represent a specific misconception. The local
  validator selects candidates that are unique, type-compatible, and different from
  the answer for every parameter combination. Supply enough usable candidates because
  generic fallback distractors are used only if model-authored candidates cannot form
  a valid set. Fallbacks are not specific to any topic profile.
- reason_template explains its misconception and may use only a bare parameter
  placeholder such as `{n}`. Do not place arithmetic or any other expression inside
  braces.
- Return only the combined proposal-and-check-plan schema and no markdown. Do not add
  locally derived fields.
"""


RESPONSE_GUIDANCE = """\
Use native JSON values matching each parameter's `kind`: integers use JSON numbers;
booleans use JSON booleans; strings use JSON strings; integer_list values use nested
JSON arrays of numbers. Do not encode numbers, booleans, or arrays as strings.
"""


def build_code_generation_request(
    request: CodeTemplateRequest,
    *,
    offered_tool_names: tuple[str, ...] = CODE_RECOMMENDED_CHECK_NAMES,
) -> StructuredGenerationRequest[PlannedGenerationResponse[CodeProposalResponse]]:
    """Return the provider-independent code proposal contract."""
    system_message = {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT}
    user_prompt = build_template_prompt(request, offered_tool_names=offered_tool_names)

    return StructuredGenerationRequest(
        messages=[
            system_message,
            {
                "role": "user",
                "content": f"{user_prompt}\n{RESPONSE_GUIDANCE}",
            },
        ],
        response_model=PlannedGenerationResponse[CodeProposalResponse],
        prompt_version=f"{CODE_TEMPLATE_PROMPT_VERSION}+response-v3",
        schema_name="template_proposal_and_check_plan",
        offered_tool_names=offered_tool_names,
    )
