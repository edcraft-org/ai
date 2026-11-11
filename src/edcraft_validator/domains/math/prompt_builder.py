"""Build math-domain prompts and the structured LLM request."""

from __future__ import annotations

from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.domains.math.math_types import (
    MAX_DISTRACTOR_CANDIDATES,
    MAX_DISTRACTORS,
    MAX_PARAMETER_VALUE,
    MAX_PARAMETER_VALUES,
    MIN_DISTRACTORS,
    MIN_PARAMETER_VALUE,
)
from edcraft_validator.domains.math.proposal_response import MathProposalResponse
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)

MATH_TEMPLATE_PROMPT_VERSION = "math-template-v1"

MATH_TEMPLATE_SYSTEM_PROMPT = """\
Generate one reusable linear-equation multiple-choice template and recommend its
fixed validation checks in the same structured response. Do not generate one concrete
question. The local application derives identity, difficulty, and question type; you
author the equation pattern, question wording, bounded parameter values, an exact
answer recipe, and distractor recipes.

Rules:
- Use the form a*x + b = c. equation_template must contain each placeholder `{{a}}`,
  `{{b}}`, and `{{c}}` and may contain no other placeholders. For example:
  "{{a}}x + {{b}} = {{c}}".
- question_template may use `{{equation}}`, `{{a}}`, `{{b}}`, and `{{c}}`. A typical
  template is "Solve for x: {{equation}}".
- Declare exactly three parameters named a, b, and c. Each has one to
  {max_values} distinct integer values from {min_value} to {max_value}. Parameter a
  must never include zero, because every equation divides by a when solving.
- Answer expressions may use the names a, b, c, and x, integer or finite decimal
  numeric literals, parentheses, the operators +, -, *, /, and unary minus. No other
  syntax is supported. For a*x + b = c, a suitable exact answer is "(c - b) / a".
  Answers are computed with exact rational arithmetic, not floating point.
- Each distractor expression must represent a specific misconception and must be
  different from the answer and from every other distractor for every declared
  parameter combination. Values such as one or negative signs can make a wrong
  operation coincide with the correct answer, so choose bounded values carefully.
  Supply at least {num_distractors} usable candidates and at most
  {max_candidates}. reason_template explains the misconception and may use only
  plain parameter placeholders such as `{{a}}`; do not put expressions inside braces.
- Select a nonempty fixed subset of the available MCP tools using their supplied
  descriptions. Use each tool name at most once and do not invent names. Supply each
  selected check's model-owned arguments using its planning schema; use {{}} for
  checks without model-owned arguments. The application freezes these arguments and
  supplies the current candidate and required distractor count. Select the structure
  check and the answers/distractors check for every reusable template. Also select
  math_assess_template_difficulty and assess_template_relevance; both are
  advisory evidence for educator review and never block a technically checked
  template.
"""

RESPONSE_GUIDANCE = """\
Use native JSON values. Parameters are objects like
{"name": "a", "values": [1, 2, 3]}. Expressions are strings such as
"(c - b) / a"; only question and equation text use placeholders.
"""


def build_math_generation_request(
    request: MathTemplateRequest,
) -> StructuredGenerationRequest[PlannedGenerationResponse[MathProposalResponse]]:
    """Return the provider-independent math proposal contract."""
    user_prompt = f"""\
Author request (preserve its meaning):
{request.prompt}

Requested difficulty: {request.difficulty}
Required usable distractors: {request.num_distractors}
Supported distractor range: {MIN_DISTRACTORS} to {MAX_DISTRACTORS}
"""
    system_prompt = MATH_TEMPLATE_SYSTEM_PROMPT.format(
        max_values=MAX_PARAMETER_VALUES,
        min_value=MIN_PARAMETER_VALUE,
        max_value=MAX_PARAMETER_VALUE,
        num_distractors=request.num_distractors,
        max_candidates=MAX_DISTRACTOR_CANDIDATES,
    )
    return StructuredGenerationRequest(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{user_prompt}\n{RESPONSE_GUIDANCE}"},
        ],
        response_model=PlannedGenerationResponse[MathProposalResponse],
        prompt_version=f"{MATH_TEMPLATE_PROMPT_VERSION}+response-v1",
        schema_name="template_proposal_and_check_plan",
        check_argument_models=(),
    )
