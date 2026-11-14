"""Build math-domain prompts and the structured LLM request."""

from __future__ import annotations

from edcraft_validator.domains.math.math_schemas import (
    MathTemplateContent,
    MathTemplateRequest,
)
from edcraft_validator.domains.math.math_types import (
    MAX_DISTRACTORS,
    MIN_DISTRACTORS,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)

MATH_TEMPLATE_PROMPT_VERSION = "math-template-v5"

MATH_TEMPLATE_SYSTEM_PROMPT = """\
Generate one reusable mathematics multiple-choice template and recommend its
fixed validation checks in the same structured response. Do not generate one
concrete question. The local application derives identity, difficulty and
question type; you author the reusable task and its wrong choices.

Return one generic item family in the `item` field.

ITEM FAMILY (`item`)
- `item.topic` is a stable dotted identifier such as `school.quadratic` or
  `university.derivative`.
- `item.parameters` declares one to six named parameters. Values are exact
  decimal or rational strings, for example "2", "-3", "1/2". Never use floats.
  Keep the product of the declared value counts at or below 512; a larger
  family cannot be swept exhaustively and is reported as inconclusive.
- `item.body` is one typed item with parameter placeholders. Its `symbols`
  declare every variable. `givens` contain relations, domain facts or finite
  data sets. `goal.kind` is one of evaluate, solve, simplify, factor, expand,
  derivative, integral, determinant. The deterministic engine grades exactly
  these goal kinds; limit and eigenvalues are not graded yet, so templates that
  use them are rejected.
- Set each payload field exactly once. A solve goal sets either `symbol` (one
  unknown) or `symbols` (two or more), never both. A domain given sets
  `kind: "domain"`, `symbol` and `domain`, and no `relation`. A relation given
  sets `kind: "relation"` and `relation`. A dataset given sets
  `kind: "dataset"` and nonempty `values`.
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
- `item.body.answer_recipe` declares the answer as typed expression trees, using
  the same closed node vocabulary as distractors; it may reference declared
  parameters. Set `kind` to numeric or expression (exactly one `items` entry),
  set or tuple (one or more `items`), or matrix. Interval and boolean answers are
  not graded yet, so templates that use them are rejected. The deterministic
  engine compiles the recipe and it must be exact for every parameter
  combination; `display` is never compared.
- For solve goals use `kind: "set"` for one unknown and `kind: "tuple"` for a
  system's ordered solution; the form check rejects other answer kinds.
- For factor and expand goals, notation is part of the answer: emit the factored
  form for factor and the fully expanded form for expand. The engine verifies
  equivalence and a separate form check verifies the shape, so an equivalent but
  wrongly-shaped recipe is rejected.
- Provide at least the requested number of distractors. Each distractor sets
  exactly one of `value` (a scalar Expr), `components` (an ordered tuple of
  Exprs), or `items` (a finite set of Exprs), plus a short `misconception` tag
  and an optional `reason`. Every distractor must be demonstrably wrong and
  distinct from every other option for every declared combination.

CHECK PLAN
- Select a nonempty fixed subset of the available MCP tools using their supplied
  descriptions. Use each tool name at most once and do not invent names. Supply
  each selected check's model-owned arguments using its planning schema; use {}
  for checks without model-owned arguments.
- Select math_verify_item_spec, math_validate_options,
  math_verify_text_fidelity, math_assess_template_difficulty, and
  assess_template_relevance.
- The fidelity check skips its model call for symbolic text and is required for
  prose text. Relevance and difficulty are advisory evidence for educator review;
  they never block a technically checked template.
"""

RESPONSE_GUIDANCE = """\
Use native JSON values. Parameter values are strings such as "2" or "1/2".
Expressions are objects such as {"op": "add", "args": [{"param": "a"},
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
    return StructuredGenerationRequest(
        messages=[
            {"role": "system", "content": MATH_TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": f"{user_prompt}\n{RESPONSE_GUIDANCE}"},
        ],
        response_model=PlannedGenerationResponse[MathTemplateContent],
        prompt_version=f"{MATH_TEMPLATE_PROMPT_VERSION}+response-v1",
        schema_name="template_proposal_and_check_plan",
        check_argument_models=(),
    )
