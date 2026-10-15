# Python tracing evaluation dataset

Use **[dataset.json](dataset.json)** as the single final reference dataset.
It contains 30 human-reviewed questions with fixed difficulty categories:

| Difficulty | Questions |
| --- | ---: |
| Easy | 13 |
| Medium | 11 |
| Hard | 6 |

The human-approved `difficulty` labels and `dimensions` ratings are authoritative.
Do not replace them with model predictions or recalculate them from the reasons.
The questions, answers, ratings, reasons, topics and splits are unchanged by the
simplification of the dataset format. Earlier reviews remain in Git history.

## Fields

The dataset records its identifier, rubric version and assessment conditions
once, followed by `questions`. Each question contains:

| Field | Purpose |
| --- | --- |
| `question_id` | Stable identifier. |
| `code`, `entry_function`, `inputs` | Program and exact input to trace. |
| `question`, `answer_target` | What the learner is asked to determine. |
| `options`, `correct_option` | Answer choices and the correct choice. |
| `difficulty`, `difficulty_reason` | Approved category and its explanation. |
| `dimensions` | Approved ratings for execution burden, changing state, conceptual interaction and answer discrimination. |
| `solution` | Explanation of the correct answer. |
| `topic`, `split` | Topic and `development`/`held_out` assignment. |
| `provenance` | Source identifier and pinned source link, for adapted questions. |

There are six questions per topic: arithmetic, conditionals, loops, functions and
lists. The existing split is 18 development and 12 reserved questions.
Review notes, confidence, alternative ratings, review bookkeeping, hashes,
execution logs and duplicate answer values are omitted. The correct answer value
is available from the option identified by `correct_option`.

Keep question content, approved categories and dimension ratings, topics and
splits fixed so evaluation results remain comparable. Git history records changes
to this dataset. Evaluation tooling and scoring are deferred.

## Attribution

Thirteen programs retain the original code from
[CRUXEval](https://github.com/facebookresearch/cruxeval/tree/190faf16d175b5847b0af05d937872b1fb395942).
Their concrete input may differ from the source example, and their question text
and answer choices were added during curation. Preserve
[CRUXEval-LICENSE](CRUXEval-LICENSE).
Three questions adapt existing EdCraft examples; fourteen were newly authored.
Adapted questions include their source identifier and link in `provenance`.
CRUXEval did not supply the difficulty labels.

The review completed on 2026-10-15 and was AI-assisted with one human reviewer.
The labels are the approved reference for this evaluation; they do not establish
independent reviewer agreement or learner-calibrated difficulty.
