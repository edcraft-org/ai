# Relevance and question quality

`assess_code_quality` v2 reviews a complete concrete Python tracing MCQ against an
explicit author request. It performs local correctness and requirement checks,
makes one batched embedding request, and can reuse an existing difficulty report.
It never starts a difficulty or quality judge call. The tool remains explicitly
invoked and tagged `quality:code`, outside template authoring's check catalogue.

## Inputs and evidence

Supply code, entry function, exact inputs, rendered question, answer target,
ordered A–C or A–D options and designated correct option. `QualityRequest` holds
`prompt`, optional `required_features`, `answer_target`, `num_distractors`, and
`learner_prerequisites`. Prerequisites provide embedding context; they do not
change an existing difficulty assessment's assumptions.

| Report section | Meaning |
| --- | --- |
| `technical` | Supported-subset and bounded execution checks, canonical answer, and distinct wrong options; passed, failed or error. |
| `requirements` | Requested reachable syntax, answer target and distractor count; satisfied, missing or unknown. |
| `similarity` | Cosine similarity between the full serialized request and learner-facing question; no pass threshold. |
| `difficulty_quality` | Optional existing difficulty report, including its quality concerns, option evidence, rubric, settings and prior usage. |

`status: assessed` means similarity was measured; `error` means that measurement
failed. Neither establishes correctness, requirement satisfaction, semantic
alignment or quality approval. Those sections must be read independently.
Syntax presence alone does not prove the requested concept affects the answer.

## Reusing difficulty evidence without another call

Pass an optional `difficulty_report` returned by `assess_code_difficulty` for the
exact same concrete question. The question SHA256 must match, including inputs,
stem, options and answer designation. A mismatch is rejected before execution or
embedding. Successful evidence must cover every supplied option and is copied so
later caller mutations cannot change the quality report.

`difficulty_quality.status` is `reused`, `not_supplied` or `unavailable`.
Missing, failed or unable-to-assess difficulty evidence is never regenerated.
Without usable evidence, `quality_concerns` is null; an empty list means an existing
successful judge reported no concerns. Failures and prior usage remain in the
nested original report. Reused usage is not new usage incurred by this call.

The difficulty judge already considers concepts, dependencies, shortcuts,
misconception hypotheses and other quality concerns. Its prompt and schema are
unchanged. It does not see the original author request, so reuse does not produce
a rubric relevance rating or establish request alignment. Template difficulty
concerns remain available in their existing template check evidence; a judgment
of a typical template instance cannot substitute for an exact concrete report.

This replaces v1's separate SocLaas quality call and `judge` output. The v2 report
has no relevance/clarity/answerability rating fields and no separate quality
rubric. `EDCRAFT_QUALITY_MODEL`, the quality provider factory and its judge deadline
have been removed. The existing difficulty provider and configuration remain.

## Embedding protocol

The provisional default is `text-embedding-3-large`, selected using the
[published model comparison](embedding-model-selection.md). Override it with
`EDCRAFT_EMBEDDING_MODEL`; configure `OPENAI_API_KEY` and optionally
`OPENAI_BASE_URL`. This selection is based on online benchmark evidence, not a
new local comparison of model accuracy.

The embedding request contains full code, inputs, stem, target and options,
excluding the answer designation. `lf-strip-v1` standardizes CRLF/CR to LF and
strips outer whitespace. There is no truncation, lowercasing or comment removal.
The report records exact compared text, model ID, revision availability, vector
dimension, cosine metric, token usage and latency. No universal cutoff is used.
An immutable weight revision is unavailable from this provider model ID.

The transport timeout is 30 seconds with zero retries. Application defaults are
35 seconds for embeddings and two for bounded execution. Errors retain available
usage without raw exception text; unknown usage stays null. Late thread results
are ignored after an application deadline. Deployment still supplies outer
isolation as described in the [developer reference](development.md).

## Fixed held-out review

```bash
uv run python scripts/evaluate_code_quality.py --env-file .env \
  --output .artifacts/relevance-v2.jsonl
```

To reuse already saved concrete difficulty reports, add
`--difficulty-reports .artifacts/difficulty.jsonl`. That file contains one
`CodeDifficultyReport` JSON object per line. Duplicate question hashes or reports
outside the frozen plan are rejected. Reports are loaded locally with no judge
requests, and the manifest records their hashes.

Protocol `code-quality-evaluation-v2-no-extra-judge` freezes the same 12 reserved
questions and seven control contents before calls. Only deterministic technical
and requirement expectations are scored. Historical rubric expectations in the
unchanged control source are not treated as measured outcomes. Ambiguity and
concept alignment receive no new rubric assessment. Existing evidence is reused
only when its exact question hash matches.

The manifest records source/dataset/control hashes, exact cases and model
settings. Each completed record is flushed to JSONL and summarized with errors,
unresolved cases, deterministic control disagreements, similarity ranges, reused
evidence availability, new embedding usage and latency. It records zero new judge
calls. Outputs cannot overwrite earlier reviews. Reference labels remain fixed.

The [original v1 review](evaluation-history.md#issue-44-relevance-and-quality-review-21-october-2026)
is historical evidence using the separate judge and small embedding model. It is
not a performance result for v2 or the new default. The held-out set has no human
relevance labels; embeddings and existing difficulty concerns cannot establish
educational validity or learner-calibrated relevance.
