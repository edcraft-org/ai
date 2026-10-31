# Evaluation

This guide covers live model calls and workflow evaluation. Run commands from the
repository root. Keep local settings in `.env` and results in `.artifacts/`;
neither should be committed. Basic test commands are in the [README](../README.md#tests).

## Live workflow smoke tests

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run --env-file .env pytest -m openai_live -q

RUN_OLLAMA_LIVE_TESTS=1 uv run --env-file .env pytest -m ollama_live -q
```

OpenAI requires `OPENAI_API_KEY`; Ollama requires a running server and `OLLAMA_MODEL`.
Both tests author a template, save and replay it, edit its wording, check the edited
template, and generate a question from it. Ollama uses reviewed finite inputs
to test the workflow separately from unconstrained question quality; the original
OpenAI smoke request leaves parameter selection to the model.
Same-repository PRs also run a live OpenAI
evaluation in CI and upload its JSONL record. A smoke test verifies one real workflow;
it does not establish general provider reliability.

## Workflow evaluation

The focused baseline for [issue 40](https://github.com/edcraft-org/ai/issues/40)
is recorded in the [evaluation results](evaluation-history.md#issue-40-baseline-10-october-2026).
The following script runs five fixed prompts: addition and conditionals (`easy`),
loop accumulation and list summation (`medium`), and a helper inside a loop (`hard`):

```bash
uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini --jobs 5 \
  --output .artifacts/authoring-natural.jsonl
```

The correction drill deliberately makes the first answer wrong, then checks whether
the model uses the tool results to fix it:

```bash
uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini --correction-drill \
  --output .artifacts/authoring-correction.jsonl
```

The drill tests correction behavior; report it separately from natural generation.
Use one primary provider/model for a baseline. Ollama and SocLaas can use the same
script via `--provider` and `--model`; SocLaas uses the OpenAI-compatible adapter.
SocLaas defaults to `SOCLAAS_RESPONSE_FORMAT=json_object`, with the response schema
included in the prompt and validated locally. `json_schema` remains configurable.
`SOCLAAS_REASONING_EFFORT=default` omits the API parameter and retains the model's
default reasoning; explicit values are passed through. Both settings are recorded.
SocLaas defaults to a 300-second request timeout and a generation/revision budget
of 16384 tokens (`SOCLAAS_GENERATION_MAX_TOKENS`). Reasoning uses the same output
budget. Truncated generations are recorded as errors with available usage preserved.
The application executes the initial frozen check plan directly through MCP; no
native-tool request or acknowledgement calls are needed. Report author generation
and revision calls separately from judge calls inside checks. Judge usage is
retained in MCP evidence, outside the top-level author usage totals.

Pre-#93 experiments used native-tool requests and acknowledgements, including a
4096-token tool budget. Preserve those records as results of that workflow version;
new runs must identify their source revision and prompt version separately. Direct
dispatch removes those authoring calls but does not change sampling algorithms,
initial-generation retry rules or the difficulty acceptance policy. A deterministic
fixture comparison against `28489b8` produced the same artifacts and check dispatches:
first-pass author calls fell from 3 to 1; a one-revision repair fell from 5 to 2.
These traces omit model-backed checks and do not establish live yield or latency gains.

Issue #95 replaces restricted distractor patches with full-proposal revision.
New authoring reports record `revision_policy=full-candidate-v1`, and code prompts
use `response-v8-full-candidate`. Preserve earlier results under their original
revision policy. A replacement may change previously valid program/wording fields;
all selected checks must run again. Record repair outcomes, request drift, tokens
and latency separately when comparing policies. This implementation change does
not establish improved yield or lower inference cost. Live benchmarks remain
separate from the deterministic verification and PR smoke tests.

Record settings when comparing runs: earlier SocLaas experiments used strict schema
mode, disabled reasoning, a 60-second timeout, and a 1024-token tool budget.
Other providers retain their request formats and defaults. Set the primary provider's
SDK retries to zero (for example `OPENAI_MAX_RETRIES=0`) for an interpretable run.

The script writes one `authoring_result` per job to JSONL and flushes after every
job. Alongside it, `.manifest.json` records the fixed cases, source revision,
working-tree status, and preview seeds; `.summary.json` records outcomes, first
attempt and correction rates, attempts per job, failure categories, median/range
latency, model calls, and token usage. Until all requested jobs are recorded, the
remaining jobs are counted as unresolved. `--jobs` controls total jobs; additional
jobs cycle through the same cases. A job can contain up to four checking attempts.

The directory with the output file's stem contains full catalogue snapshots,
successful template files, and previews at seeds 0, 1, and 42. The script reloads
each template from disk and verifies that those previews match without model or MCP
calls. All these outputs remain under ignored `.artifacts/`.

First-attempt and overall success rates use all requested jobs as the denominator.
Correction success uses jobs whose first complete attempt failed; it is `null` when
none qualify. Terminal failure counts are separate from check findings across all
attempts, including findings later repaired. Token means include unsuccessful jobs.
If any call lacks usage for a token total, that total and its mean are `null`;
`reported_input_tokens` and `reported_output_tokens` retain only the known counts.
These are technical workflow measurements, not educational-quality or difficulty
calibration scores. Report the small sample size with the observed rates.

For the historical topic/difficulty fixtures, use the CLI evaluator:

```bash
uv run python -m edcraft_validator.cli evaluate \
  --domain code --provider ollama --model qwen3.5:9b \
  --topic arithmetic --difficulty easy --repetitions 1 \
  --output .artifacts/ollama-arithmetic-easy.jsonl
```

Use `--topic all --difficulty all` for all 15 profiles. Each run uses multiple model
calls and may include revisions. Completed records are flushed to JSONL as they
finish, so they survive an interruption.

## Provisional difficulty review

Use the versioned [Python tracing difficulty rubric](difficulty-rubric.md) for
requested-versus-generated difficulty review. It defines assessment conditions,
worked anchors, evidence fields, uncertainty, template variation, and the matching
and agreement protocol to predeclare before held-out judging. Assess the level
independently, then compare it with the requested level to report `matches`,
`too_easy`, `too_hard`, or `uncertain`. Requested labels remain separate from
estimates and learner performance. Difficulty evidence is advisory and cannot
override failed technical checks.

The current [reference dataset](../reference_sets/python_tracing/README.md) uses
[v0.3](difficulty-rubric-v0.3.md), with 15 easy, 9 medium and 6 hard questions.
This is separate from the production v0.2 judge contract above. Hide reference
labels, dimensions, counts and solutions during assessment. Transport failures
are excluded from classification accuracy; content failures and missing labels
remain nonmatches. Report coverage and attempt failures separately.

See the [concise statistics](difficulty-glm-comparison-v0.3.md) and
[project log](edcraft%20logs.docx) for the results.
All 30 items informed rubric development; results are descriptive agreement, not
unseen accuracy, independent human agreement or learner calibration.

## What to report

For issue 44, see the [project report](edcraft%20logs.docx),
Section 6, for relevance checks, model selection and evaluation findings.
The v5 runner freezes all 12 reserved MCQs and seven versioned control contents,
and collects independent Python correctness, explicit requirements and shared
relevance reports. The reference and control files are unchanged.
It neither consumes difficulty reports nor makes generative judge calls.
Difficulty judgments and quality concerns remain in their separate report.
The original v1 live review is retained
as historical evidence. There are no human relevance labels for the reserved set;
the local decision does not establish Python relevance accuracy.
Earlier embedding selection is historical. Current pilot statistics are below;
local model integration tests remain opt-in.

Run the frozen review with `uv run --extra relevance python scripts/evaluate_code_relevance.py
--env-file .env --output .artifacts/relevance-v5.jsonl`.
The new protocol is `code-relevance-evaluation-v5-decision`. Reports contain
`technical`, `requirements` and `relevance`; local decision details are under
`relevance.decision`. The manifest identifies the renderer, shared tool and
review-report versions. Existing evaluation artifacts retain their original schemas.

The former `assess_code_quality` MCP name and the old script name are removed.
For a Python question, prepare shared-tool input with
`domains.code.relevance.relevance_input(question, CodeQuestionRequest(...))` and
call `assess_relevance` with that object as `request`. Call
`check_code_question_correctness(question)` and
`check_code_question_requirements(question, request)` separately when those checks
are needed. For other domains, supply an original author request and complete
textual question representation.
The shared service does not infer or enforce domain requirements. All tools reject
attached difficulty/correctness reports; no check reuses another check's judgment.
The runner continues to reject `--difficulty-reports`.
The runner retains errors and scores, flushes completed records and refuses to
overwrite earlier reviews. It never requests a replacement difficulty judgment.
It exclusively reserves the JSONL, manifest and summary files before writing any
of them. A reservation conflict removes only empty files created by that attempt;
existing evaluation evidence remains untouched.

The command exits with code 2 for incomplete measurements, protocol failures or
unexpected mandatory-check results. Held-out cases require technical checks to
pass and explicit requirements to be satisfied. Controls use their frozen
expectations, so an expected wrong-answer rejection or missing requirement is not
a run failure. `mandatory_check_failure_count` counts cases that disagree with
those expectations, including execution errors and unknown requirement results.
Run success records completed assessments and mandatory checks, independently of
the advisory relevance decision. No relevance labels exist for the reserved set.

### Local relevance pilot (issue 88, 23 October 2026)

On the same 54 [SmartSTEM](https://github.com/AmirZur/smartstem-ai) test pairs, the original Qwen prompt scored 47/54
(87.0%), versus 39/54 (72.2%) for `text-embedding-3-large`, with separate cutoffs
selected on 18 development pairs. Qwen made 1 false acceptance and 6 false
rejections; embeddings made 11 and 4 respectively. Observed median times were
50.6 ms for warm local Qwen and 547.3 ms for the hosted embedding application
path, including network/client setup. These are different deployment costs.

For the revised prompt, all previous 24 questions/72 pairs became development
data. On 12 fresh questions/36 pairs across 11 disjoint families:

| Variant | Correct | Accuracy | Balanced accuracy | False rejection / acceptance |
| --- | --- | --- | --- | --- |
| Original prompt and old cutoff | 27/36 | 75.0% | 66.7% | 7 / 2 |
| Original prompt, recalibrated | 27/36 | 75.0% | 70.8% | 5 / 4 |
| Revised prompt, recalibrated (default) | 28/36 | 77.8% | 72.9% | 5 / 3 |

The revised prompt recognizes implicitly required methods and partial coverage of
broad objectives while preserving specific restrictions. Its development-selected
cutoff is `0.0020295610011089593`; median warm time was 81.5 ms. This is a marginal
one-pair gain. Embeddings were not rerun on the fresh set. The exact revised
configuration therefore has no direct embedding comparison on that set.

A floating-point tie-break bug initially reported 30/36 for original
recalibration. Verification corrected the predeclared nearest-0.5 tie-break using
exact development counts only after holdout scoring; the table is corrected.
No prompt or cutoff was chosen from holdout outcomes.

Both pilots are curated chemistry samples with source-labelled positives and
Codex-curated negatives, without independent expert adjudication of negatives.
Three pairs share each question; two fresh questions share a parent stem.
The threshold is provisional, especially outside chemistry and on CPU FP32.
Neither Python accuracy, explicit combined requests, nor statistical superiority
is established. Only concise statistics are retained in the repository.

Use the fixed supported requests for the initial live baseline. Scripted regression
tests cover repairable and repeated failures, unsuitable check plans, invalid
arguments, and incomplete conversations. Unsupported author requests are deferred
until a concrete edge case is encountered; preserve easy/medium/hard labels.

Record the provider/model and non-secret settings, request, selected checks, attempt
history, results, and timings. For successful runs, retain the saved artifact and
preview seeds. Report selection mistakes, correction success, false
acceptance/rejection, and latency separately from schema or tool-call failures.
Keep requested difficulty separate from any future difficulty estimate or learner
performance measurement.

Keep the authoring report as the evaluation record: it contains every candidate and
full tool evidence, including failed attempts before a successful correction.
The reusable template contains only checked content, answer cases and short check
summaries. Full tool schemas are optional diagnostic output (`--tool-schemas` on
`author` or `validate`), rather than repeated in normal reports.

Evaluation JSONL contains summary fields and one `authoring_result` per completed
job. Read its reusable template at `authoring_result.artifact` and its check evidence
at `authoring_result.attempts[].executions[].evidence`. Initial generation and MCP
setup failures retain an authoring report with zero attempts. Provider-creation
failures retain their error and timing directly because no application job started.

Failure counts describe the final outcome. Earlier repaired errors stay in the
attempt history. Final-attempt argument or dispatch errors count as `TOOL_CALL_ERROR`
once per job, alongside any other final check findings. Catalogue files are linked
only after the current job writes them successfully, including when reusing an
output location. Provider failures during correction are reported separately from
failed question checks, and generation time includes unsuccessful correction calls.

See the [workflow guide](question-generation/README.md#saving-editing-and-reuse)
for saving and replaying questions, and [evaluation results](evaluation-history.md)
for the recorded baseline and historical evidence.


## Property-based checking: issue 91 (26 October 2026)

The sole template checker now uses bounded Hypothesis samples, explicit boundaries
and shrinking. Defaults: 32 generated examples, 128 total execution calls including
replay/shrinking, and 30 seconds. Passing samples is not a correctness guarantee;
generated drafts require manual review. Old exhaustive artifacts are unsupported.

A local automated smoke study passed all 15 repository example templates using
57 sampled executions in total (median 246 ms per template). All 30 injected
faults were detected: 15 wrong answer recipes and 15 colliding distractor pools.
A separate 32,768-combination arithmetic domain used 36 sampled executions in
3.60 seconds. Thirty generated drafts all used inputs outside those samples;
a separate evaluation executed those 30 drafts and found 30/30 answer agreement.
Normal generation made no execution or model calls. These are known fixtures,
synthetic faults and an automated spot-check, not human-reviewed accuracy or a
statistical confidence estimate. Small domains may happen to be fully covered by
Hypothesis; no enumeration path or full-domain coverage requirement remains.
