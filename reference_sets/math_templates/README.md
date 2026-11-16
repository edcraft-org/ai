# Mathematics template difficulty reference set

Use **[dataset.json](dataset.json)** as the single current reference set for
mathematics template difficulty. It contains 60 concrete seed-0 questions drawn
from 20 template families, rated against the provisional
[`math-ir-v0.1` rubric](../../docs/math-difficulty-rubric.md) under the
`paper-no-cas-v0.1` assessment conditions.

The ratings in this checkout are **proposed and AI drafted**. They become
reference labels only after the project owner reviews the items and fills the
owner fields. They are not calibrated against learner responses.

## Counts

| Difficulty | Questions |
| --- | ---: |
| Easy | 19 |
| Medium | 21 |
| Hard | 20 |

| Split | Families | Questions |
| --- | ---: | ---: |
| `development` | 14 | 42 |
| `held_out` | 6 | 18 |

Every family keeps all three of its items in one split. Both splits cover all
three levels, so the held-out group is not restricted to one part of the scale.
The split is by family, not by item, which keeps variants of the same template
together.

## Family coverage

| Family | Goal kind | Split | Easy | Medium | Hard |
| --- | --- | --- | ---: | ---: | ---: |
| `arithmetic-evaluate` | `evaluate` | development | 1 | 1 | 1 |
| `percentage-change` | `evaluate` | development | 1 | 1 | 1 |
| `powers-roots` | `evaluate` | development | 1 | 1 | 1 |
| `proportion-problem` | `evaluate` | development | 1 | 1 | 1 |
| `function-evaluation` | `evaluate` | development | 1 | 1 | 1 |
| `linear-equation` | `solve` | development | 1 | 1 | 1 |
| `quadratic-equation` | `solve` | development | 1 | 1 | 1 |
| `linear-system` | `solve` | held_out | 0 | 2 | 1 |
| `simplify-expression` | `simplify` | development | 1 | 1 | 1 |
| `algebraic-fraction` | `simplify` | development | 1 | 1 | 1 |
| `exponent-laws` | `evaluate` | held_out | 1 | 1 | 1 |
| `factor-quadratic` | `factor` | development | 1 | 1 | 1 |
| `factor-special` | `factor` | held_out | 1 | 1 | 1 |
| `expand-binomial` | `expand` | development | 1 | 1 | 1 |
| `expand-special` | `expand` | held_out | 1 | 1 | 1 |
| `derivative-polynomial` | `derivative` | development | 1 | 1 | 1 |
| `derivative-rules` | `derivative` | held_out | 1 | 1 | 1 |
| `integral-polynomial` | `integral` | development | 1 | 1 | 1 |
| `integral-standard` | `integral` | held_out | 1 | 1 | 1 |
| `determinant-matrix` | `determinant` | development | 1 | 1 | 1 |

The set covers all eight requested goal kinds. Most families contribute one item
at each level. `linear-system` uses two medium items and one hard item because
its easiest defensible form is already a two-step elimination.

## Fields

The dataset records its identifier, rubric version and assessment conditions
once, followed by `questions`. Each question contains:

| Field | Purpose |
| --- | --- |
| `question_id` | Stable identifier of the form `<family>-<nn>`. |
| `family` | Template family, used for the split. |
| `goal_kind` | One of the supported mathematics goal kinds. |
| `split` | `development` or `held_out`. |
| `template` | Complete `MathTemplateSpec` with parameters, body and exactly three distractors. |
| `instance` | Seed-0 production render with the question, four options and the correct option. |
| `proposed_difficulty` | Proposed overall level, `easy`, `medium` or `hard`. |
| `proposed_dimensions` | Proposed ratings for procedure length, operation type, conceptual demand and answer discrimination. |
| `proposed_reason` | The nearest rubric anchor and the structural evidence for the proposal. |
| `owner_difficulty`, `owner_dimensions`, `owner_notes` | Null until the project owner reviews the item. |

Each distractor carries a misconception tag and a short reason. The tags are
hypotheses about likely errors, not evidence from learner responses.

## Construction and checks

[`scripts/build_math_reference_set.py`](../../scripts/build_math_reference_set.py)
builds every template in code and runs the production checks before writing
anything:

1. `validate_template` checks correctness for every declared parameter
   combination in the sampled domain.
2. Form checks run for form-sensitive goals, so a factor answer is a product of
   irreducible factors and an expand answer is fully expanded.
3. Prose templates are checked with the deterministic anchor rules in
   `math_fidelity_plugin`.
4. The seed-0 instance is rendered with `generate_math_question`, the same path
   used in production.

The script fails without writing the dataset if any check fails. It preserves
filled owner fields by `question_id`, so a rebuild does not overwrite review
work. Difficulty is judged from the structure of the task, not from the size of
the numbers, which stay small by design.

## Review status

The rubric's validation plan asks for two or three independent mathematics
teachers or tutors. This set has one reviewer, the project owner, and no
independent second rater. The proposed ratings were drafted with AI assistance
and have not been independently adjudicated. `review-sheet.md` presents each
item, its options, the verified answer and the proposal so the owner can record
a level, dimensions and notes.

Until the owner fields are filled, treat these labels as advisory evidence for
educator review. Do not use them as measured learner difficulty or as an
accuracy threshold.

## Known limitations

- The build is offline and makes no model calls. Prose fidelity therefore uses
  the deterministic anchor checks only. The blind parse-back step of the
  production fidelity gate is not run, so prose agreement is weaker than a
  production authoring pass would provide.
- The set samples the declared parameter families at representative
  combinations. It does not claim that every combination has the same demand.
- Ratings are uncalibrated and rest on one reviewer.
- `exponent-laws` is recorded as an `evaluate` family rather than `simplify`
  because the production renderer folds a monomial product such as `x^3 * x^4`
  to `x^7` before display. Expressing the laws on numeric bases keeps the
  unsimplified form visible and the exponent rule genuinely part of the task.

## Regenerating

```bash
uv run python scripts/build_math_reference_set.py
uv run pytest -q tests/test_math_reference_set.py
```

The tests check the dataset shape, the production checks for all 60 templates,
the stored seed-0 instances against a fresh render, the level and split counts,
owner field preservation and the review sheet.
