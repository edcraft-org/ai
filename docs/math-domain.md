# Mathematics domain: authored recipes, engine correctness, separate form

The `math` domain authors reusable item families as a closed, typed IR. The
model authors the problem, the answer recipe and the distractor recipes; a
deterministic engine adjudicates correctness and a separate form registry
adjudicates shape. Nothing is solved or derived anywhere: the recipe the model
authors *is* the answer, and the engine grades it.

Every template has a finite parameter domain. Validation samples that domain
deterministically with a bounded property-based check: explicit boundary cases
plus seeded examples. A small domain is enumerated completely; a large one is
never materialised.

## Trust model

```text
model ──► problem IR + answer recipe + distractor recipes
                            │
                            ├──► deterministic engine ──► correct?
                            └──► form registry        ──► pass?
```

Approval requires **both** verdicts for **every sampled parameter
combination**. A domain that fits the sample budget is checked completely. The
two verdicts are recorded as separate evidence (`engine_correctness` and
`form`) and are never collapsed into one boolean.

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
  values each. The declared product is not capped; validation samples it
  instead of materialising it.
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

Technical checks gate approval:

1. `math_verify_item_spec` — schema, bounded trees, goal/answer agreement, and
   the sampled engine and form check.
2. `math_validate_options` — every distractor is demonstrably wrong, distinct
   from the key, and pairwise distinct.
3. `math_verify_text_fidelity` — prose text only; unknown placeholders, missing
   anchors and paraphrase drift.

Advisory checks never gate approval:

4. `math_assess_template_difficulty` — deterministic provisional heuristic.
5. `assess_template_relevance` — the shared semantic relevance classifier.

Advisory `failed` or `unavailable` outcomes stay visible in review evidence and
warnings; only technical failures, missing evidence, unsupported cases, or human
rejection prevent a reusable artifact.

## Validation sampling

The declared parameter domain may be very large; only a bounded sample is
graded. The sample is deterministic for a given seed and contains:

- the all-low and all-high variants;
- one variant per axis at each edge, with the other axes at both edges;
- seeded examples until the sample budget is reached.

A domain no larger than the budget is enumerated completely. If any sampled
variant fails, the template is rejected; there is no "truncated" finding and no
exhaustive-mode switch. The summary records `checking_mode="property_based"`,
the number of variants checked, the declared domain size and the seed. The
default budget is 100 variants (`MAX_IR_VARIANTS`); callers may request fewer.

Generation samples the same declared domain independently of validation, so a
generated question may use a variant that the validator did not sample. Each
emitted variant is re-graded before use.

## Generation

`generate_math_question(validated, seed)` is deterministic and performs no model,
MCP, or network call. It samples the declared domain for the requested seed, so
questions may use variants that validation did not sample. For the selected
combination it compiles the answer recipe, renders it, and then **re-grades** it:
the engine must still say `correct` and the form registry must still say `pass`.
Every distractor is re-graded as `incorrect`, and duplicate or display-identical
options are refused.

A variant that fails any gate is skipped, and a template with no usable variant
produces no question. Approval is not assumed to hold at expansion time.

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
  for any sampled combination in the declared domain.
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

The only retained read-time migration is the advisory evidence name
`math_assess_template_relevance` → `assess_template_relevance`.
