# Mathematics domain roadmap: cleanup, difficulty matrix and topic expansion

Status: proposed. This document is a plan, not an implementation record.

The current domain is deliberately narrow (`ax + b = c`, exhaustive checks). The
next step is not to add topics blindly. It is to remove the compatibility code
that the pilot accumulated, replace the ad-hoc difficulty heuristic with a
defensible rubric, make the linear-equation family genuinely varied, and only
then widen the topic catalogue.

Recommended order:

1. Cleanup (0.5-1 day)
2. Difficulty matrix v1 (1.5-2 days)
3. Better linear-equation families (2-3 days)
4. School topic expansion (4-6 days)
5. University topic expansion (8-12 days, optional)

End of step 4 is the natural "M5b" stopping point. Step 5 is a separate decision
because it needs a symbolic engine.

---

## Part A - Remove legacy and duplicated items

### A1. Legacy relevance tool

`math_assess_template_relevance` was kept only so artifacts created before
relevance became a shared capability would still load. The shared capability is
now live, so carrying a second advisory identity in domain code is dead policy.

| Item | Location | Action |
| --- | --- | --- |
| `LEGACY_MATH_RELEVANCE_TOOL` | `domains/math/math_types.py` | Delete |
| Membership in `MATH_ADVISORY_CHECK_NAMES` | `domains/math/math_types.py` | Delete; keep only difficulty + shared relevance |
| Legacy label and description | `frontend/.../checkMetadata.ts` | Delete both keys |
| Legacy frontend assertion | `checkMetadata.test.ts` | Replace with a test that unknown tools fall back to the raw name |
| Legacy schema regression | `tests/test_math_schemas.py` | Replace with a test that a failed shared-relevance verdict does not block |
| Historical artifacts | `edcraft-backend/.data/authoring/**` | One-off migration of the two local demo jobs, not a runtime alias |

Recommendation: remove the alias entirely and migrate the two local demo
artifacts. If durable read compatibility is wanted later, put a three-line
`LEGACY_CHECK_ALIASES` map in `validation/check_names.py`, never in domain code.

### A2. Duplicated types and helpers

| Duplicate | Locations | Shared home |
| --- | --- | --- |
| `Difficulty = Literal["easy", "medium", "hard"]` | `code/code_types.py`, `math/math_types.py`, `application/authoring_contracts.py` | `domains/shared/difficulty.py` |
| Placeholder parsing (`Formatter().parse`) | `code/text_rendering.py`, `math/math_schemas.py` | `domains/shared/text_template.py` |
| Parameter-combination enumeration | `math/question_generator.py`, `mcp/math_tools.py` | `domains/math/parameters.py` |
| `template_sha256` | `code/candidate_builder.py`, `math/candidate_builder.py` | `domains/shared/hashing.py` |
| Distractor/choice limits (1/3/10) | `code/code_types.py`, `math/math_types.py` | `domains/shared/limits.py` |
| `MathProposalResponse` wrapper | `math/proposal_response.py` (7 lines) | Delete; use `MathTemplateContent` directly |
| `MIN/MAX_PROMPT`, expression length limits | code and math constants | Evaluate; share only if semantics are identical |

Hard constraints for this refactor:

- `template_sha256` must produce byte-identical hashes. Add fixed-vector tests
  before moving it, because artifact IDs and approval records depend on it.
- Placeholder parsing must keep rejecting format specs, conversions and
  attribute/index access. Share the implementation, then run both domains'
  negative tests against it.
- Do not rename public tool names or wire fields in this step.

### A3. Repo-level leftovers (separate, lower priority)

Inventory, do not auto-delete: `ai-authoring-simplified-mockup.html/.png`,
`_inbox/`, duplicate difficulty docs (`difficulty-rubric.md` and
`difficulty-rubric-v0.3.md`), and copied study sources under `.artifacts/`.
Handle in a `chore/` PR after the math work, so the diff stays reviewable.

---

## Part B - Difficulty matrix

### B1. What the research supports

| Source | Contribution | Use |
| --- | --- | --- |
| Hendrycks et al. 2021, MATH dataset | 5-level ordinal difficulty, 7 subject areas | Anchor calibration and topic vocabulary |
| Webb DOK (Mathematics) | 4 levels: recall, application, strategic thinking, extended | Cognitive-demand axis |
| Revised Bloom | remember to create | Secondary cognitive vocabulary |
| Smith et al. 1996, MATH taxonomy | 3 groups / 8 categories designed for undergraduate mathematics | University topic design; better fit than Bloom alone |
| PISA 2022 | formulate / employ / interpret; 4 content categories | Context and representation axis, word problems |
| Sweller / element interactivity | difficulty rises with simultaneously processed elements | Procedural-load axis |
| Table of Specifications | topic x cognitive level grid with item counts | Batch planning UI and tests |
| CUPM 2015, CCSSM | curriculum coverage | Topic catalogue, not difficulty |
| Peters et al. 2025 review | LLM estimates promising (r ~0.87, RMSE ~0.165) but expert agreement can be low (r ~0.38) | Do not claim calibrated difficulty; keep provisional |

The key design decision: difficulty is **multi-dimensional**, but the product
still needs one of three labels. So compute dimensions, then map to a band, and
always report the dimensions so a teacher can disagree with the band.

### B2. Dimension rubric

Rate the template's **typical instance**, not the easiest or hardest variant.
Each dimension is 0-3.

| Dim | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| D1 Procedural steps | 1 operation | 2 operations | 3 operations | 4+, or strategy choice |
| D2 Element interactivity | independent elements | 2-3 held together | 4-5 held together | 6+, nested dependency |
| D3 Representation | symbolic only | verbal -> symbolic, or units | two representations (table/graph/diagram) | interpret and justify a representation |
| D4 Cognitive demand | recall / one-step procedure (DOK1, MATH A) | apply / select procedure (DOK2, MATH B) | analyze / justify / translate (DOK3, MATH C) | extended investigation / evaluate (DOK4) |
| D5 Distractor discrimination | obviously different | one plausible misconception | 2+ near misses (sign, order, coefficient) | near misses on the target misconception plus numeric closeness |

Weighted score, range 0-36:

```
S = 3*D1 + 3*D2 + 2*D3 + 3*D4 + 1*D5
```

Provisional bands: `easy <= 10`, `medium 11-17`, `hard >= 18`.

Matrix view for communication (rows D4, columns D1+D2):

| D4 \ procedural load | 0-2 | 3-4 | 5-6 |
| --- | --- | --- | --- |
| Recall | Easy | Easy | Medium |
| Apply | Easy | Medium | Medium-Hard |
| Analyze | Medium | Hard | Hard |
| Extend | Hard | Hard | Hard |

D3 and D5 act as modifiers; the weighted score is the source of truth, the
matrix is the explanation.

### B3. Linear-equation anchors

| Anchor | D1 | D2 | D3 | D4 | D5 | S | Band |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `x + 5 = 9` | 0 | 0 | 0 | 0 | 0 | 0 | Easy |
| `2x + 3 = 11` | 1 | 1 | 0 | 1 | 1 | 10 | Easy |
| `3x - 4 = 2x + 6` | 2 | 1 | 0 | 1 | 2 | 14 | Medium |
| `(3/4)x - 2 = (1/2)x + 1` | 2 | 1 | 0 | 2 | 2 | 17 | Medium |
| Taxi: `$3` plus `$2/km`, fare `$17` | 2 | 1 | 1 | 1 | 1 | 15 | Medium |
| `5 - 2(3x - 1) = 4x + 7` | 3 | 2 | 0 | 2 | 2 | 23 | Hard |

These anchors are the regression fixtures. They are provisional and must be
re-checked against teacher labels before the labels are trusted.

### B4. Implementation

- `domains/math/difficulty.py`: `DifficultyDimensions`, `MathDifficultyRubric`,
  `load_math_difficulty_rubric()`, `assess_template_dimensions(candidate)`.
- `domains/math/difficulty-rubric.md`: human-readable rubric packaged with the
  domain, mirroring `domains/code/difficulty-rubric.md`.
- Replace `_estimate_difficulty` in `mcp/math_tools.py`.
- Keep `DifficultyOutcome` unchanged for wire compatibility. Add the matrix to
  `ToolEvidence.details` only:
  `difficulty_matrix: {dimensions, weighted_score, band, provisional: true,
  calibrated: false, domain_variation}`.
- Compute dimensions deterministically from the template family, parameter
  domain and distractor taxonomy. No model call in v1. This preserves offline
  determinism and keeps the advisory gate free.
- Advisory policy is unchanged: a mismatch never blocks approval.

### B5. Calibration

1. Build 30 anchor items: 10 per band, drawn from MATH levels 1-5 and mapped to
   supported families.
2. Label with two independent raters (teacher or domain expert), blind to the
   requested difficulty.
3. Report quadratic weighted kappa and confusion matrices for heuristic, matrix
   and (optional) LLM judge.
4. Only after QWK >= 0.6 call the rubric "calibrated". Until then the evidence
   keeps `provisional: true, calibrated: false`.
5. Record the study in `docs/evaluation-history.md`, like the code domain.

If no second rater is available, keep the matrix but label it
"expert-anchored, uncalibrated" and do not publish accuracy numbers.

---

## Part C - Better math questions

> Superseded: the family-by-family design below is replaced by the spec-first
> architecture in `math-validation-architecture.md`. Keep Part C only as a
> catalogue of the equation shapes worth supporting; the validator is now
> answer-type based, not family based.

### C1. Problem today

- One equation shape only, so every batch looks the same.
- Five requested questions from an eight-combination domain repeats text.
- Distractors are free-form model expressions, so quality varies.
- Answers are often fractions even when the request implies whole numbers.
- Difficulty is inferred from coefficient size, not from what the learner does.

### C2. Question-family architecture

Introduce a `QuestionFamily` protocol. The model chooses a family, parameter
values and misconception tags; the deterministic engine computes equations,
answers, choices and explanations.

```python
class QuestionFamily(Protocol):
    id: str                      # e.g. "linear.both_sides"
    topic: str                   # e.g. "algebra.linear"
    parameters: tuple[str, ...]
    def validate(self, candidate) -> None: ...
    def solve(self, values) -> Fraction: ...
    def distractors(self, values, tags) -> list[Fraction]: ...
    def render(self, values) -> tuple[str, str]: ...   # equation, question
    def dimensions(self, candidate) -> DifficultyDimensions: ...
```

Families for M5b:

| Family | Form | Solver (exact) | Constraint |
| --- | --- | --- | --- |
| `linear.one_side` | `ax + b = c` | `(c-b)/a` | `a != 0` |
| `linear.both_sides` | `ax + b = cx + d` | `(d-b)/(a-c)` | `a != c` |
| `linear.distributive` | `a(x + b) = c` | `c/a - b` | `a != 0` |
| `linear.fraction_coeff` | `(a/b)x + c = d` | `(d-c)*b/a` | `a,b != 0` |
| `linear.divide` | `x/a + b = c` | `(c-b)*a` | `a != 0` |
| `linear.word` | context + `ax + b = c` | as one_side | clean numbers |

Deferred: inequalities (interval answers), systems (pair answers), quadratics
(multiple roots). Those need answer types, not just a new renderer.

### C3. Misconception-driven distractors

Replace free-form expressions with a fixed taxonomy:

`SIGN_ERROR`, `INVERSE_OPERATION`, `ORDER_OF_OPERATIONS`, `DISTRIBUTION`,
`ARITHMETIC_SLIP`, `COPY_CONSTANT`, `FRACTION_ERROR`, `VARIABLE_SIDE`.

Each distractor recipe carries a tag, and `distractors()` computes the value
from the tag. The structure check verifies the tag is valid for the family; the
answer check still verifies distinctness across the whole domain. This makes
wrong choices plausible and explainable, and removes a class of model errors.

### C4. Answer quality and batch variety

- `answer_kind: "integer" | "fraction" | "any"` on the request; filter parameter
  combinations to satisfy it.
- Sample combinations without replacement up to the domain size. If the request
  exceeds it, return all available variants and warn with `available_variants`
  instead of silently repeating. The UI already shows duplicates; make the cap
  explicit.
- Add `distractor_gap` evidence (distance from the answer) and reject choices
  that are trivially eliminable or numerically indistinguishable.
- Keep the misconception text as the per-choice explanation shown in review.

### C5. Prompt and schema changes

- Add `family` and `topic_id` to the proposal; keep them optional for reading
  old artifacts.
- The prompt lists families with their constraints and allowed misconception
  tags. The model no longer invents arbitrary expressions.
- Bump the prompt version and the response schema version.
- Keep `difficulty` and `question_type` fields so the backend and UI contracts
  do not change in this step.

---

## Part D - Topic expansion

### D1. What to add, in order

School (M5b), chosen for exact verifiability and curriculum value:

| # | Topic | Answer type | Effort |
| --- | --- | --- | --- |
| 1 | Arithmetic, fractions, decimals, percentages | rational / decimal | S |
| 2 | Ratio and proportional reasoning | rational | S |
| 3 | Linear equations (all families above) | rational | M |
| 4 | Linear inequalities | interval | M |
| 5 | Systems of two linear equations | ordered pair | M |
| 6 | Quadratics (factorable, formula) | root set | M |
| 7 | Sequences and series (arithmetic/geometric) | closed form / number | M |
| 8 | Functions: evaluate, intercepts, transformations | number / expression | M |
| 9 | Geometry and measurement | number + unit | S-M |
| 10 | Right-triangle trigonometry and special angles | exact value | M |
| 11 | Statistics and basic probability | rational | S-M |
| 12 | Modeling word problems (rate, mixture, work, interest) | rational | M |

University (M5c), only after the school architecture is proven:

| # | Topic | Needs | Effort |
| --- | --- | --- | --- |
| 1 | Calculus I: limits, derivatives, integrals | symbolic engine | L |
| 2 | Linear algebra: matrices, determinants, eigenvalues | exact linear algebra | L |
| 3 | Discrete math: logic, sets, combinatorics, graphs | exact counting | M |
| 4 | Probability: distributions, expectation, CLT | exact/numeric | M |
| 5 | Number theory: divisibility, modular arithmetic | exact integer | S-M |
| 6 | Sequences and series convergence | symbolic engine | L |
| 7 | Multivariable and vector calculus | symbolic engine | L |
| 8 | Abstract algebra, real analysis | proof grading | out of scope |

Recommendation: do not attempt proof-based topics. They need free-text grading
and a different evidence model.

### D2. Architecture

```
domains/math/
  topics/
    registry.py          # topic_id -> family, metadata
    school/arithmetic.py
    school/linear.py
    school/quadratic.py
    university/calculus.py
    ...
  families/base.py       # protocol, validation, registration
  misconceptions.py
  parameters.py          # combinations, answer-kind filter, novelty sampling
  difficulty.py
  difficulty-rubric.md
```

- A topic declares `topic_id`, `stage` (school/university), `answer_type`,
  `families`, and its parameter constraints.
- The prompt and the tool catalogue are generated from the registry, so adding a
  topic does not require editing prompt strings.
- Capability tags: `domain:math`, `topic:<topic_id>`, `stage:school|university`.
- The existing exhaustive-domain policy applies to every family with a small
  finite domain. Symbolic topics declare `property_based` with seeded sampling.

### D3. Symbolic engine decision

- School topics: pure Python `fractions` and closed-form solvers. No new runtime
  dependency.
- University symbolic topics: SymPy as an optional extra (`math-symbolic`),
  used by a solver adapter. Verification tests may use SymPy as an oracle even
  before it is a runtime dependency.
- Do not add SymPy to the core install for M5b. It changes startup time, image
  size and the audit surface for no school-level benefit.

---

## Part E - Verification

- Exact rational arithmetic everywhere. No floats in answers.
- Property-based tests (Hypothesis): substitute the computed answer back into
  the equation and require a zero residual for every declared combination.
- Keep exhaustive domain verification for finite families.
- Differential tests: compare school-family solvers against SymPy in tests only.
- Fixed-vector tests for `template_sha256` before and after deduplication.
- Golden tests for the matrix anchors in B3 and for distractor tags.
- Batch tests: request N > domain size, assert no silent duplicates and a
  `shortfall` warning with `available_variants`.
- Negative tests: invalid family, wrong tag, zero denominator, coincident
  distractor, ambiguous answer kind.
- End-to-end on the local stack: generate, review, approve, export; technical
  checks gate approval, advisories do not.
- Keep the suites green: validator `pytest`, Ruff, focused mypy; backend and
  frontend as pinned.

---

## Part F - Phases, effort and risks

| Phase | Deliverable | Effort | Exit criteria |
| --- | --- | --- | --- |
| 0 | Cleanup | 0.5-1 d | Legacy name gone, shared helpers extracted, suites green |
| 1 | Difficulty matrix v1 + rubric doc | 1.5-2 d | Anchors reproduce bands; evidence exposes dimensions; still advisory |
| 2 | Linear families + misconception distractors + novelty | 2-3 d | 5 families, exact solvers, no duplicate batch below domain size |
| 3 | School topics 1-6, registry, ToS planner | 4-6 d | Topic selector, mixed batch by difficulty, E2E green |
| 4 | School topics 7-12 | 2-3 d | Coverage matrix documented |
| 5 | University topics 1-3 (optional) | 8-12 d | Symbolic adapter, property-based checks, no proof grading |

Total to the end of phase 3: roughly 8-12 working days, including review
cycles. Phase 5 is a separate go/no-go.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Schema change breaks stored artifacts | High | Additive fields, `format_version` 1.1, keep reading 1.0 |
| `template_sha256` changes silently | High | Fixed-vector tests before the move; no algorithm change |
| Difficulty labels overclaimed | Medium | Provisional flags, calibration gate QWK >= 0.6, publish confusion matrix |
| Prompt/schema drift across domains | Medium | Registry-generated prompts, contract tests |
| Batch repetition persists | Medium | No-replacement sampling, explicit shortfall |
| SymPy scope creep | Medium | Optional extra, school topics stay dependency-free |
| Frontend/backend drift | Medium | Re-pin after each ai commit, run both suites |
| Legacy removal breaks demo jobs | Low | Migrate the two local artifacts before deleting |

---

## Open decisions

1. Scope: stop after school topics (phase 3), or fund university topics?
2. Legacy: migrate the two local demo artifacts and delete the alias, or keep a
   read-only alias in `validation/check_names.py`?
3. Symbolic engine: allow SymPy as an optional extra for university topics?
4. Calibration: is a second rater available, or do we ship an explicitly
   uncalibrated expert-anchored rubric?

## Sources

- Hendrycks et al., *Measuring Mathematical Problem Solving With the MATH
  Dataset*: https://arxiv.org/abs/2103.03874
- MATH dataset card (levels 1-5, subjects):
  https://huggingface.co/datasets/hendrycks/competition_math
- Kadam & Khan, IDEA difficulty estimation:
  https://www.ijmems.in/article_detail.php?article_id=763
- Webb DOK mathematics descriptors:
  https://oklahoma.gov/content/dam/ok/en/osde/documents/services/assessments/assessment-materials/Math-WebbAlign_DOK_Summary.pdf
- Smith et al. 1996 MATH taxonomy (via BSRLM):
  https://bsrlm.org.uk/wp-content/uploads/2016/02/BSRLM-IP-33-1-02.pdf
- PISA 2022 mathematics framework:
  https://pisa2022-maths.oecd.org/ and the OECD assessment framework PDF
- Element interactivity:
  https://link.springer.com/article/10.1007/s10648-023-09782-w
- Table of Specifications:
  https://files.eric.ed.gov/fulltext/EJ1005136.pdf
- CUPM 2015 curriculum guide: https://maa.org/resource/cupm-guide/
- CCSSM high-school conceptual categories: CCSSI Mathematics Appendix A
- Peters et al. 2025, LLM difficulty estimation review:
  https://arxiv.org/abs/2509.23486
- Liu et al. 2025, LLM respondents for item evaluation:
  https://bera-journals.onlinelibrary.wiley.com/doi/10.1111/bjet.13570
- SymPy-based exam generation precedent:
  https://github.com/matkoniecz/math_exam_generator
