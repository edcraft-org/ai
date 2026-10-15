# Frozen Python tracing evaluation dataset

Use **[dataset.json](dataset.json)** as the single final reference dataset.
All 30 questions completed human review on 2026-10-15. The categories are fixed:

| Difficulty | Questions |
| --- | ---: |
| Easy | 13 |
| Medium | 11 |
| Hard | 6 |

There are six questions per topic: arithmetic, conditionals, loops, functions and
lists. The family-based split is 18 development and 12 reserved questions.
Questions, answers, difficulty labels, dimension ratings, topics and splits match
the approved snapshot at Git commit `240704a`.

## Contents

Each entry in `questions` includes:

- The code, concrete input, question text, answer options and correct answer.
- `difficulty`: the fixed overall reference category.
- `dimensions`: the four fixed dimension ratings.
- `topic`, `family_id` and `split`: the organisation of the dataset.
- `difficulty_reason`, `reason_source` and `solution`: explanations and their origin.
- `provenance`: source attribution and identifiers.
- `review_notes`: human decisions, confidence and alternatives retained as context.
  These notes do not change the fixed category.
- `trace_summary`: the recorded execution evidence.

Evaluation implementation is deferred. This directory provides the dataset,
documentation and source attribution for that work.

## Frozen reference

The dataset is pinned by Git tag `python-tracing-evaluation-2026-10-15-r1`.
Its canonical JSON SHA-256 is
`046d3a20928e22b17b523ed22269cad677560dc03ef02677a283ff3cb517f23e`.

Keep question content, categories, dimension ratings, topics and splits unchanged.
Changes require an explicitly agreed new benchmark identity so previous results
remain reproducible. Metadata-only corrections use a new tag and fingerprint;
existing tags remain fixed. Earlier reviews remain available in Git history.

## Attribution and limits

Thirteen source programs come from CRUXEval revision
`190faf16d175b5847b0af05d937872b1fb395942`. Their code is unchanged, with source IDs,
links, record hashes and modification notes inside the dataset. Preserve
[CRUXEval-LICENSE](CRUXEval-LICENSE). Other items record fixture adaptation or AI
authorship. CRUXEval did not supply the difficulty labels.

The review was AI-assisted and involved one human. Public metadata omits reviewer
names and identifiers. The reference does not establish independent human
agreement or learner-calibrated difficulty. Original confidence and alternatives
remain documented without changing the fixed evaluation categories.
