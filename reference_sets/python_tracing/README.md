# Frozen Python tracing evaluation dataset

Use **[dataset.json](dataset.json)** as the single final reference for evaluation.
Keith approved all 30 questions on 2026-10-15. The categories are fixed:

| Difficulty | Questions |
| --- | ---: |
| Easy | 13 |
| Medium | 11 |
| Hard | 6 |

There are six questions per topic: arithmetic, conditionals, loops, functions and
lists. The family-based split remains 18 development and 12 reserved questions.
All questions, correct answers, difficulty labels, dimension ratings, topics and
splits match the approved snapshot at Git commit `240704a`.

## Using the data

Each entry in `questions` contains the complete code, input, stem, answer options,
correct option and verified answer. For evaluation:

- `difficulty` is the fixed overall reference category.
- `dimensions` contains the four fixed dimension ratings.
- `topic`, `family_id` and `split` organise the evaluation without moving families.
- `difficulty_reason`, `reason_source` and `solution` explain the judgment and answer.
- `provenance` records attribution and source identifiers.
- `review_notes` preserves the original human decision, confidence and alternatives.
  These notes do **not** change the fixed category or turn it into an uncertain label.
- `trace_summary` records execution evidence, including the counting conventions.

Compare a judge's predicted category with `difficulty`. Never replace reference
labels with judge outputs or recompute them from dimension ratings. Keep labels,
dimension ratings, solutions and review notes out of the judge input. The helper
below returns only the complete MCQ, including its verified correct option:

```python
from scripts.difficulty_reference import load_dataset, question_for_judge

reference = load_dataset()
for item in reference.questions:
    judge_input = question_for_judge(item)
    expected_category = item.difficulty
```

Tune on development families and freeze the judge before reserved scoring. If
reserved results inform tuning, disclose that and use a separate new evaluation
set; do not change this dataset to improve a score.

## Verification and freeze

```bash
uv run python scripts/difficulty_reference.py verify
```

The command checks the pinned dataset fingerprint, source attribution, distinct
families, correct options and execution traces. It is read-only. There is no
relabel, review-transfer or evidence-overwrite command. Primary categories also
reject reassignment on loaded question objects. Regression tests separately pin
the exact approved difficulty, dimension, topic and split assignments, so keeping
the totals while swapping individual labels is rejected.

Pin evaluation runs to Git tag `python-tracing-evaluation-2026-10-15` and the
reported dataset fingerprint. The tag also preserves the earlier review history.

Do not edit this final dataset. Any future correction requires an explicitly
agreed new benchmark identity, with this reference preserved for prior results.
The original reviews and superseded collections are recoverable from Git history;
they are no longer active dataset files.

## Attribution and limits

Thirteen source programs come from CRUXEval revision
`190faf16d175b5847b0af05d937872b1fb395942`. Their code remains unchanged, with source
IDs, links, record hashes and modification notes inside the dataset. Preserve
[CRUXEval-LICENSE](CRUXEval-LICENSE). The other items record fixture adaptation or
AI authorship. CRUXEval did not supply the difficulty labels.

These are fixed, human-confirmed evaluation categories under the recorded manual
tracing conditions. The review was AI-assisted and involved one human. It does
not establish independent human agreement or learner-calibrated difficulty.
Freezing the labels makes evaluations comparable; it does not erase their
original uncertainty or guarantee every learner will find them equally difficult.
