# Python tracing evaluation dataset

Use **[dataset.json](dataset.json)** as the single final reference dataset.
It contains 30 questions with AI-assisted ratings updated on 22 October 2026
under the user-approved v0.3 ordinary-trace rules:

| Difficulty | Questions |
| --- | ---: |
| Easy | 15 |
| Medium | 9 |
| Hard | 6 |

The reference `difficulty` labels and `dimensions` ratings use user-approved
boundaries, with an AI-assisted item-by-item review. They are authoritative for
this evaluation, rather than independently human-validated learner difficulties.
Do not replace them with model predictions or recalculate them from the reasons.
Question content, answers, topics and historical splits are unchanged. Ratings
and reasons follow [v0.3](../../docs/difficulty-rubric-v0.3.md).
The exact v0.3 snapshot is preserved in
[archive/dataset-v0.3.json](archive/dataset-v0.3.json). The superseded v0.4
experiment is retained in [archive/dataset-v0.4.json](archive/dataset-v0.4.json).
Both versions use the same overall and dimension labels. The exact previous
v0.2 dataset is preserved in [archive/dataset-v0.2.json](archive/dataset-v0.2.json).
The two overall changes are `arithmetic-reassignment-01` and
`lists-endpoint-swap-02`, both medium to easy. Model disagreements must not
rewrite this frozen reference.

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
| `dimensions` | Approved ratings for execution burden, changing state and conceptual interaction; option quality is separate. |
| `trace_event_count` | Verified target-relevant event count under the v0.3 convention. |
| `solution` | Explanation of the correct answer. |
| `topic`, `split` | Topic and `development`/`held_out` assignment. |
| `provenance` | Source identifier and pinned source link, for adapted questions. |

There are six questions per topic: arithmetic, conditionals, loops, functions and
lists. The historical split is 18 development and 12 held-out questions. All 30 have now
been inspected during rubric development, so neither group is an unseen test.
Use fresh families for a subsequent independent generalisation evaluation.
Dataset-level review metadata records the approved boundary rulings. Per-item
execution records are produced by `scripts/difficulty_trace.py`. The correct answer value
is available from the option identified by `correct_option`.

Keep question content, approved categories and dimension ratings, topics and
splits fixed so evaluation results remain comparable. Git history records changes
to this dataset. Run the explicitly opt-in SoCLaaS evaluation using
`scripts/compare_soclaas_difficulty.py`; see the v0.3 model-comparison section in
[the evaluation guide](../../docs/evaluation.md). Existing production MCP judging
retains its v0.2 contract and is not the request evaluated by this script.

## Attribution

Thirteen programs retain the original code from
[CRUXEval](https://github.com/facebookresearch/cruxeval/tree/190faf16d175b5847b0af05d937872b1fb395942).
Their concrete input may differ from the source example, and their question text
and answer choices were added during curation. Preserve
[CRUXEval-LICENSE](CRUXEval-LICENSE).
Three questions adapt existing EdCraft examples; fourteen were newly authored.
Adapted questions include their source identifier and link in `provenance`.
CRUXEval did not supply the difficulty labels.

The original review completed on 2026-10-15 with AI assistance and one human
reviewer. The v0.3 revision followed the AI-assisted consistency audit and
user-approved operational rulings on 2026-10-22.
The labels are the approved reference for this evaluation; they do not establish
independent reviewer agreement or learner-calibrated difficulty.
