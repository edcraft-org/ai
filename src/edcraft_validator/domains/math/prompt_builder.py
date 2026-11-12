"""Build math-domain prompts and the structured LLM request."""

from __future__ import annotations

from edcraft_validator.domains.math.math_schemas import (
    MathTemplateContent,
    MathTemplateRequest,
)
from edcraft_validator.domains.math.math_types import (
    MAX_DISTRACTOR_CANDIDATES,
    MAX_DISTRACTORS,
    MAX_PARAMETER_VALUE,
    MAX_PARAMETER_VALUES,
    MIN_DISTRACTORS,
    MIN_PARAMETER_VALUE,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)

MATH_TEMPLATE_PROMPT_VERSION = "math-template-v2"

MATH_TEMPLATE_SYSTEM_PROMPT = """\
Generate one reusable mathematics multiple-choice template and recommend its
fixed validation checks in the same structured response. Do not generate one
concrete question. The local application derives identity, difficulty and
question type; you author the reusable task and its wrong choices.

Return exactly one authoring mode:
1. The generic `item` field for any mathematics topic. This is the normal path.
2. The legacy linear fields only when the request is exactly one equation of the
   form a*x + b = c. Never return both modes.

GENERIC MODE (`item`)
- `item.topic` is a stable dotted identifier such as `school.quadratic` or
  `university.derivative`.
- `item.parameters` declares one to six named parameters. Values are exact
  decimal or rational strings, for example "2", "-3", "1/2". Never use floats.
- `item.body` is one typed item with parameter placeholders. Its `symbols`
  declare every variable. `givens` contain relations, domain facts or finite
  data sets. `goal.kind` is one of evaluate, solve, simplify, factor, expand,
  derivative, integral, limit, determinant, eigenvalues.
- Expressions are closed data trees, never code. A node sets exactly one of:
  {"num": "3"} for an exact number, {"sym": "x"} for a variable, {"param": "a"}
  for a template parameter, or {"op": "add", "args": [...]} for an operator.
  Supported operators are add, sub (2 args), mul, div (2 args), pow (2 args),
  sqrt, abs, exp, sin, cos, tan, asin, acos, atan, log.
- `item.body.text.template` is learner-facing text. It may use declared parameter
  placeholders such as `{a}` and these reserved placeholders:
  `{expr}` (the goal expression), `{equation}` (the first relation),
  `{equations}` (all relations), and `{matrix}` (the goal matrix).
  Escape literal braces by doubling them. Use `mode: "symbolic"` whenever the
  text is fully rendered by the deterministic renderer.
- Omit `item.body.answer` so the solver derives the key. If you do declare one,
  it must agree with the solver for every parameter combination.
- Provide at least the requested number of distractors. Each distractor sets
  exactly one of `value` (a scalar Expr), `components` (an ordered tuple of
  Exprs), or `items` (a finite set of Exprs), plus a short `misconception` tag
  and an optional `reason`. Every distractor must be demonstrably wrong and
  distinct from every other option for every declared combination.
- `item.body.validation.primitives` names the comparison used for the derived
  key: `solution_set` for solve goals, `expression_equiv` for expressions,
  `numeric` for numbers, `matrix_vector` for matrices, `collection` for sets or
  lists. More than one primitive is allowed.

LEGACY LINEAR MODE
- Use the form a*x + b = c. equation_template must contain each placeholder
  `{a}`, `{b}`, and `{c}` and may contain no other placeholders. For example:
  "{a}x + {b} = {c}".
- question_template may use `{equation}`, `{a}`, `{b}`, and `{c}`.
- Declare exactly three parameters named a, b, and c. Each has one to
  {max_values} distinct integer values from {min_value} to {max_value}. Parameter
  a must never include zero.
- Answer expressions may use a, b, c, and x, integer or finite decimal numeric
  literals, parentheses, +, -, *, /, and unary minus. For a*x + b = c, use
  "(c - b) / a". Answers are computed with exact rational arithmetic.
- Supply at least {num_distractors} usable distractor candidates and at most
  {max_candidates}. reason_template may use only plain parameter placeholders.

CHECK PLAN
- Select a nonempty fixed subset of the available MCP tools using their supplied
  descriptions. Use each tool name at most once and do not invent names. Supply
  each selected check's model-owned arguments using its planning schema; use {}
  for checks without model-owned arguments.
- For generic mode select math_verify_item_spec, math_validate_options,
  math_verify_text_fidelity, and assess_template_relevance. Do not select the
  legacy structure, answers/distractors, or difficulty checks.
- For legacy linear mode select math_verify_template_structure,
  math_validate_answers_and_distractors, math_assess_template_difficulty, and
  assess_template_relevance.
- The fidelity check skips its model call for symbolic text and is required for
  prose text. Relevance and difficulty are advisory evidence for educator review;
  they never block a technically checked template.
"""

RESPONSE_GUIDANCE = """\
Use native JSON values. Parameter values are strings such as "2" or "1/2".
Generic expressions are objects such as {"op": "add", "args": [{"param": "a"},
{"sym": "x"}]}; only learner-facing text uses `{...}` placeholders.
"""


def build_math_generation_request(
    request: MathTemplateRequest,
) -> StructuredGenerationRequest[PlannedGenerationResponse[MathTemplateContent]]:
    """Return the provider-independent math proposal contract."""
    user_prompt = f"""\
Author request (preserve its meaning):
{request.prompt}

Requested difficulty: {request.difficulty}
Required usable distractors: {request.num_distractors}
Supported distractor range: {MIN_DISTRACTORS} to {MAX_DISTRACTORS}
"""
    system_prompt = MATH_TEMPLATE_SYSTEM_PROMPT
    for name, value in {
        "max_values": MAX_PARAMETER_VALUES,
        "min_value": MIN_PARAMETER_VALUE,
        "max_value": MAX_PARAMETER_VALUE,
        "num_distractors": request.num_distractors,
        "max_candidates": MAX_DISTRACTOR_CANDIDATES,
    }.items():
        system_prompt = system_prompt.replace("{" + name + "}", str(value))
    return StructuredGenerationRequest(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{user_prompt}\n{RESPONSE_GUIDANCE}"},
        ],
        response_model=PlannedGenerationResponse[MathTemplateContent],
        prompt_version=f"{MATH_TEMPLATE_PROMPT_VERSION}+response-v1",
        schema_name="template_proposal_and_check_plan",
        check_argument_models=(),
    )
