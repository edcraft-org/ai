# Mathematics domain: bounded linear equations

The `math` domain authors and expands one-step and two-step linear equations of
the form `ax + b = c`. It is deliberately narrow: every supported template has a
finite parameter domain that can be checked exhaustively before a human approves
it.

## Scope

- One unknown, `x`.
- Integer coefficients `a`, `b`, and `c` from a declared finite set.
- `a` is never zero, so every combination has exactly one rational solution.
- Answers and distractors are evaluated as exact `fractions.Fraction` values; no
  floating-point approximation is used.
- Templates and seeds are reusable: the same validated artifact and seed always
  produce the same equation, choices, and correct index without a model, MCP, or
  external I/O call.

## Template contract

A math template declares:

- `equation_template`: exactly the canonical `{a}x + {b} = {c}` form
  (whitespace is ignored). Other layouts, including `x^2`, unknowns on both
  sides, or reordered terms, are rejected.
- `question_template`: text that may use `{a}`, `{b}`, `{c}`, and `{equation}`.
- `parameters`: exactly three named parameters `a`, `b`, and `c`, each with
  1–6 unique integer values in `[-100, 100]`. `a` must not include zero.
- `answer_expression`: an arithmetic expression in `a`, `b`, and `c` whose exact
  value equals `(c - b) / a` for every parameter combination.
- `distractors`: 1–12 recipes, each an arithmetic expression and a misconception
  reason. The saved artifact keeps only the recipes that passed checking.
- `difficulty`: `easy`, `medium`, or `hard` (advisory, see below).

Text placeholders accept bare names only; format specifications and attribute or
index access are rejected.

## Supported expressions

Expressions may contain:

- parameter names `a`, `b`, `c` (and `x` where the expression is evaluated with a
  value for it),
- integer and finite float literals,
- `+`, `-`, `*`, `/`, unary minus, and parentheses.

Examples that are supported: `(c - b) / a`, `c / a - b`, `-(b + c) / a`.

Unsupported syntax is rejected rather than interpreted: function calls,
comparisons, boolean operators, exponentiation, comprehensions, attribute access,
subscripts, strings, and any other name. Constants are bounded, expressions are
limited to 100 syntax nodes and 500 characters, and nesting is bounded.

## Check plan

Two technical checks gate approval:

1. `math_verify_template_structure` — placeholders, parameter domain, expression
   allowlist, and bounds.
2. `math_validate_answers_and_distractors` — enumerates every parameter
   combination, computes the exact answer, and requires every answer to be
   well-defined, every distractor to differ from the answer, and all choices to
   be pairwise distinct.

Two advisory checks never gate approval:

3. `math_assess_template_difficulty` — a deterministic, provisional heuristic.
4. `math_assess_template_relevance` — conservative keyword overlap between the
   author request and the template.

Advisory `failed` or `unavailable` outcomes stay visible in the review evidence
and warnings, but only technical failures, missing evidence, unsupported cases,
or human rejection prevent a reusable artifact.

## Difficulty rubric

The heuristic scores five signals, one point each:

- coefficient `a` has magnitude greater than 1;
- any parameter value is negative;
- any parameter magnitude is at least 10;
- the parameter domain has at least 60 combinations;
- the template declares at least 4 distractors.

Score 0–1 is `easy`, 2–3 is `medium`, and 4–5 is `hard`. This mapping is a
provisional scaffold for the pilot, not a calibrated difficulty model. A mismatch
is advisory and is recorded separately from technical correctness.

## Unsupported cases

- Equations with the unknown on both sides, powers of `x`, fractions with `x` in
  a denominator, systems of equations, and word problems requiring an external
  diagram.
- Non-integer parameter values and unbounded parameter ranges.
- Templates whose distractor coincides with the answer for any combination in the
  declared domain.
- Templates that need a model, tool, or Python execution at expansion time.

These cases must be rejected by the technical checks rather than silently
approximated.
