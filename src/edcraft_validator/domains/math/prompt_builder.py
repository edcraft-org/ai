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

MATH_TEMPLATE_PROMPT_VERSION = "math-template-v10"

MATH_TEMPLATE_SYSTEM_PROMPT = """\
Generate one reusable mathematics multiple-choice template and recommend its
fixed validation checks in the same structured response. Do not generate one
concrete question. The local application derives identity, difficulty and
question type; you author the reusable task and its wrong choices.

Return one generic item family in the `item` field.

ITEM FAMILY (`item`)
- `item.topic` is a stable dotted identifier such as `school.quadratic` or
  `university.derivative`.
- `item.parameters` declares one to twelve named parameters. Values are exact
  decimal or rational strings, for example "2", "-3", "1/2". Never use floats.
  Give each parameter a broad, ordered value list: up to 512 values per axis is
  allowed, and a large declared family produces more distinct questions.
  Validation samples the declared family with boundary and seeded cases, so do
  not shrink a domain to fit an exhaustive sweep. A revision keeps or widens the
  declared domain and must not drop values only to avoid a failure, unless the
  value is genuinely invalid for the task.
- Include negative, zero, positive and fractional values where the task supports
  them, and keep the extremes meaningful. Sampling always checks both ends of
  every value list, so a value that breaks the item is a real defect.
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
- A parameter and a symbol must have different names. A text placeholder such
  as `{n}` refers to a parameter, while an expression node `{"sym": "n"}` refers
  to a symbol; reusing one name for both makes the generated question and its
  answer disagree.
- Every declared parameter must be referenced by an expression node or a text
  placeholder. A parameter that never appears adds no variation to the family
  and is rejected.
- Expressions are closed data trees, never code. A node sets exactly one of:
  {"num": "3"} for an exact number, {"sym": "x"} for a variable, {"param": "a"}
  for a template parameter, or {"op": "add", "args": [...]} for an operator.
  Supported operators are add, sub (2 args), mul, div (2 args), pow (2 args),
  sqrt, abs, exp, sin, cos, tan, asin, acos, atan, log. An exponent must be a
  bounded integer literal with absolute value at most 12, never a symbol or a
  parameter; the deterministic engine does not evaluate symbolic powers.
- `item.body.text.template` is learner-facing text. It may use declared parameter
  placeholders such as `{a}` and these reserved placeholders:
  `{expr}` (the goal expression), `{equation}` (the first relation),
  `{equations}` (all relations), and `{matrix}` (the goal matrix).
  Write any expression or equation that contains a parameter through a reserved
  placeholder, never as prose around parameter placeholders such as
  `(x + {a})`, because a negative value would then read as `x + -3`. Use a
  parameter placeholder only for a standalone number.
  Escape literal braces by doubling them. Use `mode: "symbolic"` whenever the
  text is fully rendered by the deterministic renderer.
- `item.body.answer_recipe` declares the answer as typed expression trees, using
  the same closed node vocabulary as distractors; it may reference declared
  parameters. Set `kind` to numeric or expression (exactly one `items` entry),
  set or tuple (one or more `items`), or matrix. Interval and boolean answers are
  not graded yet, so templates that use them are rejected. The deterministic
  engine compiles the recipe and it must be exact for every sampled parameter
  combination; `display` is never compared.
- For solve goals use `kind: "set"` for one unknown and `kind: "tuple"` for a
  system's ordered solution.
- For factor and expand goals, notation is part of the answer: emit the factored
  form for factor and the fully expanded form for expand. The engine verifies
  equivalence and a separate form check verifies the shape, so an equivalent but
  wrongly-shaped recipe is rejected. For factor the answer recipe must itself be
  a product of factors, for example `(x - 2)*(x - 3)`, never the expanded
  polynomial `x^2 - 5*x + 6`; for expand it must be the expanded polynomial,
  never a product.
- Provide exactly the requested number of distractors; fewer is rejected and
  extra ones are dropped. Each distractor sets
  exactly one of `value` (a scalar Expr), `components` (an ordered tuple of
  Exprs), or `items` (a finite set of Exprs), plus a short `misconception` tag
  and an optional `reason`. Every distractor must be demonstrably wrong and
  distinct from every other option for every sampled combination.

CHECK PLAN
- Select a nonempty fixed subset of the available MCP tools using their supplied
  descriptions. Use each tool name at most once and do not invent names. Supply
  each selected check's model-owned arguments using its planning schema; use {}
  for checks without model-owned arguments.
- The application always runs math_verify_item_spec and math_validate_options.
  It also runs math_verify_text_fidelity for prose text and
  math_verify_answer_form for factor and expand goals, whether or not you
  select them.
- Select assess_template_difficulty and assess_template_relevance. They are
  advisory evidence for educator review and never block a technically checked
  template. The difficulty rubric is provisional and uncalibrated.
- For other goals, select math_verify_answer_form only when the request asks for
  the answer in a particular shape.
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
