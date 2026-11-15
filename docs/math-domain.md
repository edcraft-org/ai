# Mathematics domain: authored recipes, engine correctness, separate form

The `math` domain authors reusable item families as a closed, typed IR. The
model authors the problem, the answer recipe and the distractor recipes; a
deterministic engine adjudicates correctness and a separate form registry
adjudicates shape. Nothing is solved or derived anywhere: the recipe the model
authors *is* the answer, and the engine grades it.

Every template has a finite parameter domain. Validation checks that domain
with the shared Hypothesis property checker: explicit boundary examples run
first, a small domain is enumerated completely, and a larger domain is checked
within a limited budget. The full product is never materialised.

## Trust model

```text
model ──► problem IR + answer recipe + distractor recipes
                            │
                            ├──► deterministic engine ──► correct?
                            └──► form registry        ──► pass?
```

Each verdict comes from its own check and is saved as its own evidence
(`engine_correctness` from `math_verify_item_spec`, `form` from
`math_verify_answer_form`). Correctness is required for every template. Form is
required for `factor` and `expand` goals, where notation is part of the answer,
and is optional for other goals. A required verdict must hold for **every
checked parameter combination**. A domain that fits the budget is checked
completely.

Refusals fail closed:

| Oracle | Passing value | Anything else |
| --- | --- | --- |
| engine `CorrectnessResult.outcome` | `correct` | `incorrect`, `unknown`, `unsupported`, `timeout`, `error` all reject |
| form `FormResult.status` | `pass` | `fail` and `unsupported` both reject |

So a construct the engine cannot represent (`AdapterGap`) rejects the template
instead of being skipped.

## Template contract (`math-ir/0.1`)

A template declares `topic`, one to twelve `parameters`, and one `body`.

- `parameters`: named values as exact decimal or rational strings, at most 512
  values each. The declared product has no schema limit. Validation checks it
  within a limited budget instead of materialising it.
- `body.symbols`: every variable, with domain facts (`real`/`integer`/`rational`,
  `positive`, `nonzero`).
- `body.givens`: relations and domain facts. Finite data sets are accepted by
  the schema but have no engine representation, so such an item is refused.
- `body.goal`: `kind` plus the expression, symbol(s), point, or matrix it needs.
- `body.answer_recipe`: the answer, as typed expression trees (see below).
- `body.distractors`: one to ten recipes, each `value` (scalar), `items`
  (finite set) or `components` (ordered tuple), plus a `misconception` tag.
- `body.text.template`: learner-facing text using declared parameter placeholders
  and the reserved `{expr}`, `{equation}`, `{equations}` and `{matrix}`.

Expressions are closed data trees, never code. A node sets exactly one of
`num` (exact literal), `sym` (variable), `param` (template parameter) or `op`
with `args`. Supported operators: `add`, `sub`, `mul`, `div`, `pow`, `sqrt`,
`abs`, `exp`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `log`. Trees are
bounded in nodes and depth; literal exponents are bounded to absolute value 12.

## Answer recipes

`AnswerRecipe` mirrors `Distractor`: it is data, and it may reference declared
parameters, so one recipe is correct for every combination.

| `kind` | Payload |
| --- | --- |
| `numeric`, `expression` | exactly one `items` entry |
| `set`, `tuple` | one or more `items` |
| `matrix` | `matrix` |
| `interval` | `interval` (not graded yet; rejects) |
| `boolean` | `boolean` (not graded yet; rejects) |

`display` is never compared. The engine compiles the recipe and decides. Every
item and template body must declare an `answer_recipe`; it is the only answer
representation in the IR.

## Correctness

The adapter maps the IR onto the deterministic engine's closed operations:

| IR goal | Engine operation |
| --- | --- |
| `evaluate`, `simplify`, `expand`, `factor` | same name |
| `derivative` | `differentiate` |
| `integral` | `antiderivative` |
| `solve` | `solve` (relation givens, `solve_for`, declared domain) |
| `determinant` | `determinant` |

The engine returns one of `correct`, `incorrect`, `unknown`, `unsupported`,
`timeout`, `error`. Only `correct` passes, for answers and for every variant.

Distractors are graded the same way, but the required verdict is inverted: a
distractor must be `incorrect`. An `unknown` or `unsupported` distractor cannot
be proven wrong, so it rejects the template.

There is no second derivation and no solver in the domain. A model that authors a
wrong recipe is rejected rather than corrected.

## Form

The engine grades mathematical equivalence, so `expand`, `factor` and `simplify`
accept the same answer set. The form registry is what distinguishes them.

| Goal | Required shape |
| --- | --- |
| `expand` | a polynomial in the declared symbols, fully expanded, with no unexpanded power of a sum |
| `factor` | a product of irreducible polynomial factors of degree at least two, already factored |
| `derivative` | a plain expression with no unevaluated `Derivative` |
| `integral` | a plain expression with no unevaluated `Integral` |
| `solve` | a `set` for one unknown, an ordered `tuple` for a system |
| `determinant` | a finite numeric scalar |
| `evaluate`, `simplify` | a compilable expression answer |

For `expand` and `factor` the rule applies to distractors as well: a factored
answer next to expanded options gives the answer away, so an option with the
wrong shape is rejected even when it is numerically wrong.

The form rule is not advisory and a model cannot repair it: a recipe with the
wrong shape rejects the template.

## Check plan

Technical checks gate approval. `MathDomain.required_checks` decides which
ones a candidate needs, and the application adds any that the model did not
select:

1. `math_verify_item_spec` — always required. Schema, bounded trees,
   goal/answer agreement and the property-based engine check.
2. `math_validate_options` — always required. Every distractor is demonstrably
   wrong, distinct from the key, and pairwise distinct.
3. `math_verify_answer_form` — required for `factor` and `expand` goals. The
   answer and every distractor have the shape the goal demands. The model may
   select it for other goals.
4. `math_verify_text_fidelity` — required for prose text. Unknown placeholders,
   missing anchors and paraphrase drift. Anchors are checked against the
   authored text, and the blind parse-back reads one substituted variant.

The application also compares the number of distractors with the request. Too
few is reported to the author model as a failed check
(`application_distractor_count`). Extra distractors are dropped when the
candidate is built, so a generated question has exactly the requested number.

Finalisation packages the evidence these isolated checks returned. It does not
run validation again in the application process.

Advisory checks never gate approval:

5. `assess_template_difficulty` — the shared provisional difficulty cascade, using
   the `math` rubric (document version `math-ir-v0.1`).
6. `assess_template_relevance` — the shared semantic relevance classifier.

Advisory `failed` or `unavailable` outcomes stay visible in review evidence and
warnings; only technical failures, missing evidence, unsupported cases, or human
rejection prevent a reusable artifact.

## Validation sampling

The declared parameter domain may be very large. Validation uses the shared
Hypothesis property checker in `validation/property_checks.py`, the same
checker the code domain uses. It receives:

- the declared values of each parameter, in declaration order
- explicit boundary examples, checked first: the all-first and all-last
  combinations, each parameter at its last value with the others at their
  first value, and 0 where 0 is an allowed value

A domain that fits the budget is enumerated completely, so every combination is
checked. A larger domain is checked within the budget and the full product is
never materialised. The default budget is 100 examples (`MAX_IR_VARIANTS`), and
callers may request fewer.

If a generated combination fails, the template is rejected. The property checker
shrinks that combination and reports it in a `variant <parameters>:` finding.
Explicit boundary examples run before generated samples, and Hypothesis does not
shrink them, so a failing boundary example is reported exactly as declared.
Exhausting the execution-call or wall-clock budget is also a failure
(`PROPERTY_CHECK_BUDGET_EXCEEDED`) and records no partial pass. The summary records
the shared property-check coverage (`checking_mode`, `examples_checked`,
`execution_calls`, the checking budgets, `whole_domain` and `seed`) plus the
template's declared domain size. Generation samples the same declared domain
independently, so a generated question may use a variant that validation did
not check. Each emitted variant is rendered from the approved recipes.

## Generation

`generate_math_question(validated, seed)` is deterministic and performs no model,
MCP, or network call. Each generated question also carries LaTeX for the
equation, choices, answer and prompt segments, so the frontend can typeset it
with KaTeX. It samples the declared domain for the requested seed, so
questions may use variants that validation did not check. For the selected
combination it compiles the answer recipe and every distractor recipe, renders
them, and rejects unusable option combinations:

- duplicate choices, by value or by display text;
- a choice that repeats the key;
- a template that declares no distractors.

A rejected combination is skipped and the next parameter combination is tried,
and a template with no usable combination produces no question.

Generation does not re-grade. The authoring-time checks are the evidence that
the answer is correct and in the required form, so the approved recipes are
trusted in the same way the code domain trusts the recipe it is given. The engine
and the form registry are asked only while a template is being approved, never
again at expansion time.

## Unsupported cases

These reject rather than approximate:

- `limit` and `eigenvalues` goals — no engine operation.
- `interval` and `boolean` answers — no engine answer kind.
- Power operations whose exponent is a symbol. The engine evaluates a power only
  once its exponent is an exact number: a parameter exponent is bound first and
  supported, while a symbolic exponent is refused.
- Determinant matrices whose entries are not exact numbers after binding.
- Authoring parameters as `sym` nodes instead of `param` nodes.
- Templates whose distractor coincides with the key, or repeats another option,
  for any checked combination in the declared domain.
- Templates that need a model, tool, or Python execution at expansion time.

## Retired: the bounded linear-equation authoring mode

The `equation_template` / `question_template` / `answer_expression` /
`distractors` authoring fields, the linear IR module, and the safe arithmetic
evaluator are removed. Proposals carrying those fields are rejected. Legacy
linear artifacts cannot be re-validated, because the evaluator that produced
their keys no longer exists; they must be re-authored as IR templates.

The SymPy primitive oracles, model-facing witnesses and the test-only topic
fixture package are also removed. Correctness is decided only by the engine and
shape only by the form registry; option collision checks use one internal
distinctness helper.
