# A general validation method for math questions

Status: implemented for V0-V7 (school and university symbolic topics). The Lean
proof track is deferred. This document supersedes the family-by-family approach
in `math-domain-roadmap.md` Parts C and D.

## 1. The short answer

There is a general way to validate math questions, but it is not a universal
solver and it is not a list of question families. It is three things:

1. **A typed math IR** (JSON, closed vocabulary, exact rationals) that describes
   the problem: symbols, givens, goal, answer type, distractors, text anchors.
2. **Answer-type primitives** that check the formal object: numeric,
   expression equivalence, solution set, interval, collection, quantity, matrix,
   string/choice, proof.
3. **A two-key gate**: the formal gate (deterministic, CAS-backed) and the
   NL-fidelity gate (blind parse-back + anchors). Any "unknown" goes to a human.

The topic does not determine the validator. The **answer type** does. A
quadratic, a percentage and a linear system all reduce to "solve a constraint
set, compare an answer object". That is what makes the method general.

SymPy is the right runtime backend for the computational slice, roughly 60-75%
of school and early-university items, if it is used behind a typed IR and a
tri-state result. Lean is not a general validator; it is a proof track and an
offline audit tool. Neither engine validates that the English text means what
the equation says. That needs a separate gate.

## 2. Why families do not scale

A family-per-shape design fails in three ways:

- **Combinatorial growth.** `ax+b=c`, `ax+b=cx+d`, `a(x+b)=c`, `(a/b)x+c=d`,
  `x/a+b=c`, inequalities, systems, quadratics, and then the same for geometry,
  calculus and discrete math. Each family duplicates solver, renderer, tests and
  difficulty logic.
- **The validator is the wrong place to specialize.** The hard part is not "is
  this a linear equation"; it is "is the answer set correct, is every distractor
  wrong, and does the text express the same problem". Those are answer-type
  questions.
- **It hides the NL problem.** A new family validator still cannot tell whether
  the stem faithfully describes the equation. Adding families adds surface area
  without closing the gap.

Instead: **many thin generators, one validator**. A topic is a declarative
scenario that produces a spec. The validator dispatches on answer type and never
knows the topic.

## 3. The pipeline

```
                 ┌──────────────────────────────────────────────┐
 model           │  MathItemSpec (typed JSON IR)                │
 (or template)   │  symbols · givens · goal · answer type ·     │
                 │  distractors · text · anchors · validation   │
                 └──────────────────────┬───────────────────────┘
                                        │
                    L0 schema + type gate (deterministic)
                                        │
                    L1 formal gate (deterministic, CAS)
                    solve · unique? · answer · distractors ·
                    domain · units · variant sweep
                                        │
                    L2 NL-fidelity gate (independent)
                    constrained render OR blind parse-back ·
                    canonical diff · anchors · ambiguity
                                        │
              ┌─────────────────────────┴─────────────────────────┐
              │                                                   │
        pass both keys                                     any unknown/mismatch
              │                                                   │
        L3 advisory (difficulty, relevance, readability)     L4 human review
              │                                                   │
        approve-ready                                        quarantine
```

Approval requires **both** L0-L1 and L2. A formal pass with an NL mismatch is
quarantined, not approved. Advisory evidence never blocks approval by itself;
the technical gate and the fidelity gate do.

## 4. The math IR

The IR is the contract. It is data, not code. The model never emits Python,
SymPy source or executable LaTeX. The validator compiles the IR to SymPy
internally with a closed operator table.

Minimum schema:

| Field | Purpose |
| --- | --- |
| `schema_version` | Versioned; readers accept the previous minor version |
| `topic` | Curriculum metadata, not validation logic |
| `symbols[]` | Name, kind (unknown/given), domain (real/integer/rational), assumptions (positive, nonzero, integer) |
| `givens[]` | Relations (`eq`/`ne`/`lt`/`le`/`gt`/`ge`), symbol domains, finite data sets |
| `goal` | Goal kind, symbol(s), expression, point, order, domain, or matrix |
| `answer` | Optional declared answer; the solver derives the key independently |
| `distractors[]` | Candidate wrong answers, each with a misconception tag |
| `text` | Mode (symbolic/prose), stem template, plus IR-node-to-character anchors |
| `validation` | Which primitives to run and their parameters |

`Given` has no figure payload and `Goal` has no unit or tolerance field. Figures
and Lean proof payloads are deferred; `proof` exists only as a primitive name
that always returns `inconclusive`.

Example (linear equation, values as exact strings, no floats):

```json
{
  "schema_version": "math-ir/0.1",
  "topic": "algebra.linear",
  "symbols": [
    {"name": "x", "kind": "unknown", "domain": "real"}
  ],
  "givens": [
    {"id": "g1", "kind": "relation", "relation": {
      "kind": "eq",
      "lhs": {"op": "add", "args": [
        {"op": "mul", "args": [{"num": "2"}, {"sym": "x"}]},
        {"num": "3"}
      ]},
      "rhs": {"num": "11"}
    }}
  ],
  "goal": {"kind": "solve", "symbol": "x", "domain": "real"},
  "distractors": [
    {"value": {"num": "7"}, "misconception": "INVERSE_OPERATION"},
    {"value": {"num": "4"}, "misconception": "SIGN_ERROR"}
  ],
  "text": {
    "mode": "symbolic",
    "template": "Solve for x: 2x + 3 = 11",
    "anchors": {}
  },
  "validation": {
    "primitives": [
      {"type": "solution_set", "params": {"domain": "real", "unique": true}},
      {"type": "expression_equiv", "params": {"normal_form": "any"}}
    ]
  }
}
```

Rules:

- **The answer is derived, not asserted.** The model supplies givens and goal;
  the validator solves. This removes a whole class of "model states the wrong
  answer" errors. For MCQs, the model supplies distractor values or
  misconception tags, and the validator checks each one is wrong.
- **Closed vocabulary.** Unknown `op` is a hard error. Bounded node count and
  depth. No recursion, no user-defined functions, no attribute access.
- **Exact numbers only.** Decimal literals are parsed as rationals
  (`Rational("0.1") == 1/10`). Floats never enter the tree.
- **Assumptions are explicit.** `domain` and `assumptions` are part of the
  spec, not inferred from the text.
- **Anchors are mandatory.** Every quantity in the IR maps to a text span, and
  every number in the text maps to an IR node. Without anchors, NL fidelity is
  unfalsifiable.
- **LaTeX is a render target, never the interchange format.**

## 5. Answer-type primitives

These are the reusable checks. The topic picks a combination; it does not write
a new validator.

| Primitive | Parameters | Backend | Used by |
| --- | --- | --- | --- |
| `numeric` | abs/rel/sigfigs/decimals, tolerance, rounding | pure Python `Decimal` | arithmetic, measurement, stats |
| `expression_equiv` | normal form (any/expanded/factored), timeout | SymPy, guarded | algebra, trig, calculus |
| `solution_set` | equation/inequality, domain, unique, multiplicity | SymPy `solveset` + substitute-back | equations, inequalities, systems |
| `collection` | ordered/unordered, multiplicity, partial credit | pure Python | roots, tuples, lists |
| `interval` | open/closed, domain | pure Python | inequalities, domain/range |
| `quantity` | unit policy (required/optional/ignore), dimension | `pint` or dimension table | physics-style, measurement |
| `matrix_vector` | shape, per-entry primitive | pure Python + SymPy | linear algebra |
| `string_choice` | exact/normalised/regex/edit distance | pure Python | MCQ key and distractors |
| `proof` | statement + proof term + axioms allowlist | Lean 4, offline | proof track only |

Cross-cutting rules:

- **Tri-state results**: `pass`, `fail`, `inconclusive`, plus `reason` and
  `evidence`. `inconclusive` blocks auto-approval and routes to review; it is
  not a failure.
- **Compare sets, not expressions**, for equations and inequalities.
- **Substitute back** every candidate solution into the original constraints.
  SymPy's `solveset` can return extraneous roots for log and sqrt equations.
- **Timeout in a separate process.** SymPy has no timeout; `signal.alarm` only
  works in the main thread. Use a process pool with hard termination.
- **Ban unsound shortcuts**: `force=True` in `expand_log`/`powdenest`,
  `native_decide` in Lean, and `simplify` as an oracle.
- **Method parameters are part of the answer key** (tolerance, normal form,
  units policy). The same student answer can be right or wrong depending on the
  declared method; make it explicit.

## 6. What SymPy can and cannot do

Verified capabilities and caveats from the research:

| Area | Works | Fails or needs care |
| --- | --- | --- |
| Arithmetic | exact rationals, gcd/lcm/mod, order of operations | floats; parse decimals as rationals |
| Expression equivalence | structural, `cancel`, `simplify`, numeric falsification | `simplify` is incomplete; `equals()` returns `None` |
| Equations | `solveset(..., domain=Reals)` | extraneous roots; `ConditionSet`; parameterized cases |
| Inequalities | `solve_univariate_inequality`, `reduce_inequalities` | multi-variable; `x**2 < n` with symbolic `n` |
| Systems | `linsolve`, `nonlinsolve` | large symbolic systems; case analysis |
| Calculus | derivatives, integrals, limits, series; verify antiderivative by differentiating | non-elementary integrals; `AccumBounds`; piecewise |
| Linear algebra | det, rank, rref, nullspace, eigenvals | large symbolic matrices; proofs |
| Number theory | primality, factorization, CRT, modular inverse | certificates; unbounded `factorint` |
| Logic | propositional `satisfiable`, `simplify_logic` | first-order reasoning |
| Stats | standard distributions, `P`, `E`, `Var` | `Abs` conditions can raise; rewrite as intervals |
| Units | conversion | `meter + second` returns an unevaluated sum, not an error |
| Geometry | coordinates, lengths, areas, intersections | synthetic proof, construction validity |
| Proof | almost nothing | Lean track or human rubric |

Measured integration benchmark: SymPy completed about 65% of a 705-problem
integral suite, versus Mathematica 100%, FriCAS 93.9%, Maple 93.1%, Giac 84.3%,
Maxima 80.1%. SymPy is good enough for coursework, not for arbitrary closed
forms.

**Verdict:** SymPy is the primary runtime backend, behind the IR, with a
tri-state API and a hard timeout. Add Giac as an optional second opinion for
integrals and limits, not as a dependency of the core.

## 7. What Lean can and cannot do

Lean 4 + Mathlib is a soundness oracle for **propositions**, not a question
validator.

- **Strong:** algebra, order, analysis, linear algebra, number theory,
  combinatorics, measure-theoretic probability. Tactics like `ring`, `linarith`,
  `omega`, `norm_num`, `field_simp`, `positivity` are fast and reliable.
- **Weak or absent for school use:** synthetic geometry (LeanEuclid covers
  Euclid Book I + ~125 problems), statistics/data analysis, numerical methods,
  modelling, units, "explain your reasoning".
- **The bottleneck is autoformalization faithfulness, not proof search.**
  Prover-only numbers are high (miniF2F ~90%+), but end-to-end NL-to-verified
  numbers are much lower (miniF2F ~36% end-to-end before statement repair).
  Typechecking alone detects only ~11% of statement drift; human audit of
  faithfulness remains required.
- **Engineering cost:** Mathlib import is ~15 s cold (~60 s on constrained CI),
  the cache is ~10 GB, and per-proof checking is fast only with a warm REPL.
  A per-question cold Lean container is not viable for a demo web app.

**Verdict:** do not adopt Lean as the general validator. Use it for an optional
proof track and for offline audits of high-stakes banks. For those, store the
formal statement, pin the toolchain and Mathlib commit, ban `native_decide`,
and require a separate NL-faithfulness review.

## 8. The NL-fidelity problem

This is the part the user's proposed pipeline misses. Validating the equation
does not validate the question.

Evidence:

- Equation-to-text generation reaches roughly 45-56% equation consistency
  (generated text parsed back to the source equation), with a parser-oracle
  ceiling of 67-77%. Roughly half of generated texts do not express the fixed
  equation.
- Educational generators can be highly solvable (94.8%) while conceptually
  correct only 78.8% of the time. Solvable is not the same as good.
- Autoformalization precision is high but recall is low (reported precision
  ~98%, recall ~48%). A checker that only says "pass" when confident is right
  to be conservative.
- Question-validity ensembles reach high precision (~92%) at moderate recall
  (~51%). The honest output is pass / fail / unknown, and unknown is common.

So the fidelity gate must be built, not assumed:

1. **Preferred: constrained realization.** Render the stem from the IR with
   typed slots and a grammar. The text is a projection of the IR, so drift is
   structurally impossible. Less variety, but safe.
2. **For variety: free generation + blind parse-back.** A second model, which
   has not seen the IR, parses the stem back into an IR. Canonicalize both,
   compare symbol sets, constraint sets, goal and answer sets, and check the
   anchors. Any mismatch or multiple valid parses goes to quarantine.
3. **Do not use one parser as the judge.** Parser recall is the ceiling.
   Disagreement between two parsers is a quarantine signal, not a rejection.
4. **Never let the generation model approve its own text.** Use a different,
   pinned model for the parse-back. LLM judges may flag, never approve.

### 8.1 The `FidelityPlugin` protocol

The engine and the fidelity check are domain-neutral. Only the plugin knows the
artifact and what "the same problem" means. Math implements the first plugin;
chemistry and biology can implement the same protocol without changing the
engine.

```python
class FidelityPlugin(Protocol):
    domain: str
    artifact_model: type[BaseModel]
    evidence_strength: Literal["deterministic", "probabilistic"]

    def requires_check(self, artifact: BaseModel) -> bool: ...
    def reconstruction_request(
        self, text: str
    ) -> StructuredGenerationRequest[Any]: ...
    def check_anchors(
        self, artifact: BaseModel, text: str
    ) -> FidelityVerdict: ...
    def canonicalize(self, artifact: BaseModel) -> CanonicalArtifact: ...
    def equivalent(
        self, expected: BaseModel, reconstructed: BaseModel
    ) -> FidelityVerdict: ...
```

- `requires_check` lets constrained realization skip the model call. Math skips
  symbolic templates and requires a parse-back only for prose items.
- `check_anchors` runs before any model call. A structural anchor failure never
  reaches the parser.
- `canonicalize` produces the digest used for caching and for stating what was
  compared.
- `equivalent` is the semantic quarantine gate. It returns tri-state: a
  counterexample is `failed`, an undecidable comparison is `inconclusive`, and
  only a positive structural match is `passed`.
- A chemistry plugin would set `artifact_model = ChemicalItemSpec` and compare
  structures or balanced reactions. A biology plugin would set
  `evidence_strength = "probabilistic"` and compare a claim graph; it must never
  claim deterministic approval.

The engine (`application/fidelity/engine.py`) calls the plugin through
`run_judge`, caches reconstructions by text and expected-artifact digest, and
maps every judge error to `inconclusive`, never to `passed`. The math plugin
lives in `domains/math/fidelity.py`.

The corresponding MCP tools are additive; the existing tool names and artifact
format 1.0 remain stable:

| Tool | Purpose |
| --- | --- |
| `math_verify_item_spec` | Compile and solve an IR item or sweep a finite template |
| `math_validate_options` | Option-level MCQ checks against the derived key |
| `math_verify_text_fidelity` | Blind parse-back plus anchor and ambiguity checks |

## 9. MCQ-specific validation

Deterministic, option-level checks:

- Exactly one key.
- Every distractor is **demonstrably wrong** under the declared primitive.
- No two options are equivalent under any declared primitive (guards against
  two correct answers).
- Each distractor records a **misconception tag** (sign, inverse operation,
  order of operations, distribution, arithmetic slip, copy constant, fraction,
  variable side). A distractor that fails for an unarticulated reason is a
  quality defect.
- Options are type- and unit-homogeneous; no length or grammar cues; the key is
  not systematically the longest.
- No answer leakage in the stem or in another item's rationale.
- No "all/none of the above" by default.

This matters because LLM distractor quality is reported around 52%, and
multiple-correct-answer detection is weak (F1 0.00-0.46). Do not delegate these
checks to a judge.

## 10. Topic tiers

"Any math question" is not achievable in one gate. Be explicit about coverage.

| Tier | Topics | What gates approval |
| --- | --- | --- |
| A | Arithmetic, fractions, percentages, ratios, linear/quadratic equations, unit conversion, simple probability with an explicit sample space | L0 + L1 + L2 (constrained realization), near-autonomous |
| B | Systems, inequalities, sequences, combinatorics with stated assumptions, descriptive statistics | L0 + L1 + L2, plus human sampling |
| C | Geometry with diagrams, modelling with real-world assumptions, multi-part items | Declarative figure spec + L1, human review mandatory |
| D | Formal proof, informal proof, open modelling, rubric-graded responses | Lean proof track or human rubric; no auto-approval |

Tier C needs a **declarative figure spec** (points, segments, constraints,
labels) rendered by the system; an image cannot be validated. Tier D is a
separate product surface.

## 11. How a topic plugs in

A topic is a generator, not a validator:

```python
class TopicGenerator(Protocol):
    topic_id: str
    stage: Literal["school", "university"]
    answer_primitive: str
    def generate(self, *, seed: int) -> MathItemSpec: ...
```

- The generator emits a spec. It does not solve, render or validate.
- The shared engine solves the spec, validates it, and renders or parse-backs
  the text.
- The topic registry feeds the prompt and the tool catalogue. Adding a topic is
  a new generator plus tests, not a new gate.
- Difficulty and relevance are computed on the spec, so they work for every
  topic.

This is the concrete replacement for "families": **answer types are the
families**.

## 12. Build plan

| Phase | Work | Effort | Exit criteria |
| --- | --- | --- | --- |
| V0 | IR schema + closed-vocabulary compiler to SymPy | 2-3 d | Linear equation round-trips; unknown ops rejected; no `eval` |
| V1 | Primitives: numeric, expression_equiv, solution_set, collection, interval, string_choice | 3-5 d | Tri-state results; substitute-back; process timeout |
| V2 | Declarative test harness (key + wrong witness + invalid witness + variant sweep) | 2-3 d | A failing witness blocks approval; STACK-style |
| V3 | Migrate the existing linear domain to IR + generic gate | 1-2 d | Parity with current suite; no wire changes |
| V4 | NL fidelity gate: constrained renderer, then blind parse-back + anchors | 2-3 d | Mismatch quarantines; anchors enforced |
| V5 | MCQ option checks + misconception tags | 1-2 d | Two-correct and duplicate options rejected |
| V6 | Prove generality with 3 topics: percentages, quadratics, systems | 3-5 d | Same engine, no per-topic validator |
| V7 | University symbolic track (calculus, linear algebra), no Lean | 3-5 d | Same engine; derivative and determinant topics validate |

Total to V6: roughly 3-4 weeks including review. V7 is a separate go/no-go.

## 13. What changes in the current roadmap

- Drop the `QuestionFamily` per-shape validators. Keep thin generators.
- Drop the "5 linear families" milestone. Replace it with IR V0 and the
  generic gate.
- The difficulty matrix moves onto the IR: dimensions are computed from the
  spec, so it generalizes with the validator.
- The topic expansion becomes generator work, not validator work.
- The cleanup phase is unchanged and still first.

## 14. Risks and guardrails

| Risk | Guardrail |
| --- | --- |
| IR too narrow, topics need escapes | Versioned extension points; closed core; review new ops |
| IR too broad, becomes a language | Bounded node count/depth; no recursion or user functions |
| Model emits unsafe code | Never accept Python/SymPy; compile JSON IR internally |
| CAS hangs | Process pool, hard timeout, resource caps |
| CAS says unknown | Tri-state; unknown blocks auto-approval |
| NL drift | Constrained realization by default; blind parse-back for variety |
| Parser recall ceiling | Two parsers; disagreement quarantines; human sample |
| LLM judge bias | Never approve with a judge; different pinned model for parse-back |
| Overclaimed accuracy | Report per-flaw-type recall; publish the human-review rate |
| Proof topics | Lean track only; pin toolchain; human audit of faithfulness |

## 15. Recommendation in one paragraph

Build a **spec-first, solve-then-render, two-key validator**. The model emits a
typed JSON math IR, not SymPy code. The system derives the answer, checks it
with answer-type primitives backed by SymPy in a sandboxed worker, verifies
every distractor and option, and renders the stem from the IR (or free-generates
and blind-parses it back). Approval needs both the formal key and the fidelity
key; any unknown goes to human review. Topics are thin generators over the same
IR, so adding a topic never adds a validator. Lean is reserved for proof
obligations and offline audits, not the runtime. This is the only design that is
general without pretending to be omniscient.

## 16. Research signals (verify before quoting externally)

The numbers below come from the research reports and should be spot-checked
against the primary sources before publication.

| Claim | Signal |
| --- | --- |
| Equation-to-text consistency | ~45-56% ACC-eq; parser oracle ~67-77% |
| Educational generation | ~94.8% solvable vs ~78.8% conceptual correctness |
| Autoformalization | ~98% precision, ~48% recall; ~31% of ports had formalization errors |
| Question validity | ~92% precision at ~51% recall |
| MCQ QA | ~94% label accuracy but ~38% exact match; multi-correct F1 0.00-0.46 |
| Distractors | ~52% accuracy |
| Lean end-to-end | miniF2F ~36% end-to-end before statement repair; typecheck detects ~11% of drift |
| SymPy integrals | ~65% completion on a 705-problem suite |
| Human label noise | inter-annotator kappa ~0.30-0.34 |

The kappa figure is the important one: no gate can be more reliable than its
labels. Keep human review permanent and publish the review rate.

## Sources

SymPy and CAS:

- SymPy simplification, `simplify`, gotchas, assumptions, `solveset`, parsing:
  https://docs.sympy.org/latest/
- Math-Verify: https://github.com/huggingface/Math-Verify
- `latex2sympy2_extended`: https://github.com/huggingface/latex2sympy2_extended
- CAS integration benchmark (SymPy ~65%):
  https://www.12000.org/my_notes/CAS_integration_tests/
- MathJSON: https://mathlive.io/math-json/ ; OpenMath: https://openmath.org/technical/

Lean and autoformalization:

- Lean tactic reference: https://lean-lang.org/doc/reference/latest/
- Mathlib: https://leanprover-community.github.io/
- miniF2F: https://github.com/openai/miniF2F
- ProofNet: https://arxiv.org/abs/2302.12433
- Lean Workbook: https://arxiv.org/abs/2406.03847
- FormalMATH: https://arxiv.org/abs/2505.02735
- PutnamBench: https://arxiv.org/abs/2407.11214
- Kimina Lean Server: https://arxiv.org/abs/2504.21230
- LeanEuclid: https://github.com/loganrjmurphy/LeanEuclid

NL generation and fidelity:

- Wang, Lan, Baraniuk 2021, equation-to-text:
  https://arxiv.org/abs/2109.04546
- MATHWELL 2024: https://arxiv.org/abs/2402.15861
- EDUMATH 2025/2026: https://arxiv.org/abs/2510.06965
- Poiroux et al. 2025, autoformalization: https://arxiv.org/abs/2406.07222
- MathQ-Verify / ValiMath: https://arxiv.org/abs/2505.13903
- MCQ QA review: https://aclanthology.org/2026.aimecon-wip.58/
- AIE: https://arxiv.org/abs/2608.06609
- Self-preference: https://arxiv.org/abs/2404.13076
- Self-verification limits: https://arxiv.org/abs/2402.08115

Assessment platforms:

- STACK answer tests: https://docs.stack-assessment.org/en/Authoring/Answer_Tests/
- STACK question tests and deployment:
  https://docs.stack-assessment.org/en/Authoring/Authoring_workflow/
- WeBWorK MathObjects answer checkers:
  https://wiki.openwebwork.org/wiki/Answer_Checkers_(MathObjects)
- Möbius authoring: https://www.digitaled.com/support/help/admin/Content/INST-AUTHORING/
- Wolfram `AssessmentFunction`:
  https://reference.wolfram.com/language/ref/AssessmentFunction.html
- GeoGebra `Prove`: https://geogebra.github.io/docs/manual/en/commands/Prove/
- Perseus expression widget: https://github.com/Khan/perseus
