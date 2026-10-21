# Relevance and question quality

`assess_code_quality` reviews a complete concrete Python tracing MCQ against an
author request. It is an explicitly invoked MCP tool tagged `quality:code`; it is
not selected by template authoring and does not change saved-template validation.
The Python entry point is
`application.code_quality.assess_code_question_quality`.

## Input and evidence

Supply the same complete question shape as `assess_code_difficulty`: code,
entry function, exact inputs, rendered question, answer target, ordered A–C or A–D
options, and designated correct option. Supply a `QualityRequest` containing:

| Field | Meaning |
| --- | --- |
| `prompt` | Original learning objective or author request; required. |
| `required_features` | Optional explicit supported syntax requirements. |
| `answer_target` | Optional requested execution target. |
| `num_distractors` | Optional requested count, two or three. |
| `learner_prerequisites` | Semantic knowledge assumed during rubric judging. |

The report preserves four independent evidence sections:

| Section | Interpretation |
| --- | --- |
| `technical` | Supported-subset, bounded execution, canonical answer, and distinct wrong-option checks. `passed`, `failed`, or `error`. |
| `requirements` | Reachable syntax features, target and option count. `satisfied`, `missing`, or `unknown`. Syntax alone cannot prove the concept matters to the answer. |
| `similarity` | Embedding cosine similarity between the serialized request and full learner-facing question. No pass threshold. |
| `judge` | Advisory relevance, clarity, answerability and evidence for every option, with concerns and uncertainty. |

`status: assessed` means both semantic measurements completed; it is not approval
or a correctness pass. `partial` retains one successful semantic measurement and
the other one's error; `error` means neither completed. Always inspect the technical
and requirement sections independently. Failed or unavailable correctness evidence
and missing explicit requirements cannot be repaired by similarity or good rubric
ratings. There is no aggregate quality score or automatic acceptance decision.

Unsupported code is rejected before execution. Execution uses the existing local
worker and its process limits. Missing count-target trace data returns error
evidence. Production deployment still supplies outer isolation as described in the
[developer reference](development.md).

## Similarity and rubric protocol

The default embedding model ID is `text-embedding-3-small`; configure
`EDCRAFT_EMBEDDING_MODEL`, `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL`.
The report records the model ID, revision availability, vector dimension, metric,
exact compared text, usage and latency. The provider exposes a model ID rather
than an immutable weight revision; the report states that limitation explicitly.
`lf-strip-v1` replaces CRLF and CR with LF and strips outer whitespace. No content
is truncated, lowercased or removed from code, inputs, stem, target or options.
The correct-option designation is excluded from embeddings because it is not
learner-facing. Long requests rejected by the embedding endpoint remain errors.

The rubric and prompt are versioned in `domains/code/quality.py`, and the report
hashes the exact rubric text. The SocLaas model uses `EDCRAFT_QUALITY_MODEL` or
`SOCLAAS_MODEL`, plus the existing SocLaas transport/output settings. The judge sees
the request, prerequisites and full MCQ, including the answer designation as
unverified context. It does not see similarity, execution results, source identity,
human difficulty labels, dimension ratings or reference solutions.

Each dimension uses `good`, `concern` or `unknown`, with evidence. Exact-option
schemas require evidence for every supplied choice. Distractor misconceptions are
hypotheses, not learner observations. The rubric asks whether the requested concept
is necessary to derive the answer, rather than merely mentioned in comments or
unused code. Uncertainty and quality concerns remain separate lists.

There is one application judge call and one batched embedding call per assessment.
The embedding transport has a 30-second timeout and zero retries. Application
defaults are 60 seconds for judging, 35 for embeddings and two for execution.
Failures retain available token usage without raw exception text. An application
deadline ignores late results; it cannot terminate a synchronous provider thread.
Unknown usage remains null. Judge adapter retries are recorded separately in its
settings; the frozen evaluation requires zero retries.

## Fixed held-out review

Run from the repository root after configuring the two services:

```bash
SOCLAAS_MAX_RETRIES=0 SOCLAAS_RESPONSE_FORMAT=json_schema \
SOCLAAS_TIMEOUT_SECONDS=110 \
uv run python scripts/evaluate_code_quality.py --env-file .env \
  --output .artifacts/quality-review.jsonl
```

The script freezes its manifest before calls. It reviews all 12 reserved questions
from the unchanged `reference_sets/python_tracing/dataset.json`, plus seven
versioned engineering controls in `quality-controls.json`: relevant, off-topic,
omitted explicit requirement, topic words without the requested concept, ambiguous
wording, wrong answer and duplicate distractor. The control expectations are fixed
before judging and hidden from the judge. No control changes a frozen MCQ.

The manifest contains exact cases, dataset/control/source hashes, Git revision,
provider IDs, settings and deadlines. Sampling remains at provider defaults, with
no seed or temperature claim. Each completed record is flushed immediately to
JSONL; a summary retains unresolved cases, errors, control disagreements, separate
rating counts, similarity ranges, token totals and median latency. Settings drift
is recorded as a protocol failure, never discarded or silently accepted. Output
paths cannot overwrite an earlier or partial review.

The held-out dataset has human difficulty labels but no human relevance or quality
labels. This run is a descriptive review, not a quality-accuracy estimate. Controls
are engineering hypotheses rather than independent human reference judgments. A
single judge and a small fixed set cannot establish educational validity. Preserve
unexpected ratings, uncertainty and weak distractor evidence for human review;
do not tune a cutoff or rewrite reference labels from these results. Deeper
educational calibration remains later work.

The first fixed review and its observed disagreements are recorded in the
[21 October 2026 evaluation results](evaluation-history.md#issue-44-relevance-and-quality-review-21-october-2026).
