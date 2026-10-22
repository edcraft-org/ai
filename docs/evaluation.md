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
SocLaas defaults to a 300-second request timeout, with generation and tool/receipt
budgets of 16384 and 4096 tokens (`SOCLAAS_GENERATION_MAX_TOKENS` and
`SOCLAAS_TOOL_MAX_TOKENS`). Reasoning uses the same output budget. Truncated
generation and tool responses are recorded as errors, with available usage preserved.
All providers are asked to batch the pending native tool calls. OpenAI-compatible
requests use `tool_choice=required` and `parallel_tool_calls=true`. The application
executes the calls against the same candidate and collects every result before
requesting a correction. Incomplete batches request only the remaining checks;
they cannot skip validation. Call records retain the requested function names and
arguments. Compare actual multi-call turns, success rates, and total job usage:
allowing batching does not guarantee the model returns multiple calls.
Record settings when comparing runs: earlier SocLaas experiments used strict schema
mode, disabled reasoning, a 60-second timeout, and a 1024-token tool budget.
Other providers retain their request formats and defaults. Set the primary provider's
SDK retries to zero (for example `OPENAI_MAX_RETRIES=0`) for an interpretable run.

The script writes one `authoring_result` per job to JSONL and flushes after every
job. Alongside it, `.manifest.json` records the fixed cases, source revision,
uncommitted-source hash, and preview seeds; `.summary.json` records outcomes, first
attempt and correction rates, attempts per job, failure categories, median/range
latency, model calls, and token usage. Until all requested jobs are recorded, the
remaining jobs are counted as unresolved. `--jobs` controls total jobs; additional
jobs cycle through the same cases. A job can contain up to three checking attempts.

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

## v0.3 ordinary-trace reference agreement

The issue 86 revision uses [the v0.3 ordinary-trace rubric](difficulty-rubric-v0.3.md)
and 30 revised reference questions: 15 easy, nine medium and six hard. Shortcuts
do not lower difficulty. Three difficulty dimensions replace the previous four;
answer-option quality remains separate. The exact previous dataset is archived at
`reference_sets/python_tracing/archive/dataset-v0.2.json`.

Run this opt-in evaluation from the repository, with the configured SoCLaaS key:

```bash
uv run python scripts/evaluate_trace_difficulty.py --env-file /path/to/.env \
  --model qwen3.6:35b --repetitions 2 --concurrency 2 --timeout 180 \
  --output /path/to/new-evidence-directory
```

The directory must not exist. Before generation, a manifest freezes all 60 planned
assessments, source/data/rubric hashes, complete blinded requests and schemas,
explicit model ID, accessible catalogue and non-secret settings. There is one call
per assessment, zero SDK/application retries, strict JSON schema, model-default
reasoning/sampling, a 16,384-token output budget and a 180-second transport timeout.
The shared judge deadline is five seconds longer. No expected level, dimension,
event count, reference explanation, question ID or split is sent to the model.

`records.jsonl` retains each parsed assessment, raw API response, returned model,
usage, errors, latency and reference. It flushes each completed record and updates
`summary.json`; final `predictions.csv` supports report tables. Errors and unknowns
are primary-accuracy nonmatches, and unfinished jobs remain unresolved in the
planned denominator. Valid-only agreement is separate. Per-dimension agreement,
exact event-count agreement, confusion counts, per-class precision/recall/F1,
severe disagreements, repeat stability and rule-consistency findings are retained.
Output differences do not trigger reference edits, prompt tuning or reruns.

The percentile interval uses 2,000 bootstrap resamples of exact code families,
retaining repeated assessments together, with seed 86. It is descriptive for this
small, purposive reference; related nonidentical programs can remain correlated.
Catalogue-based metering estimates are not a claim of out-of-pocket charges.

All 30 items, including the historical held-out group, informed rubric review.
Report these results as descriptive agreement with an AI-assisted reference and
user-approved boundaries, not independent held-out accuracy or learner calibration.
Existing production MCP judging and authoring retain their v0.2 prompt/schema and
policy; this explicitly versioned offline v0.3 request is a different configuration.

### Transport retries and current accuracy policy

The preceding full-run command reproduces the initial bounded r1 protocol.
For the user-requested follow-up, use the original run as immutable input:

```bash
uv run python -m scripts.retry_trace_difficulty_transport \
  --env-file /path/to/.env --parent /path/to/original-run \
  --output /path/to/new-retry-evidence-directory
```

This follows the three original transport failures only. It disables HTTP and
judge deadlines using explicit `None`, keeps SDK retries at zero, replays each
exact frozen request once and records redacted underlying error diagnostics.
It cannot disable an upstream service limit. Other predictions are never retried.

The current accuracy policy excludes transport-failed slots from the denominator
and reports classification coverage and transport attempt failures separately.
Other errors and abstentions remain nonmatches. The combined 60-slot view replaces
only each targeted slot with its new attempt, irrespective of the prediction;
all original records remain intact. A protocol manifest, raw retry records, merged
records, CSV and summary identify this follow-up separately from the initial run.
See [the report](evaluation-history.md) for both configurations and their results.

## Original v0.2 provisional difficulty review

Use the versioned [Python tracing difficulty rubric](difficulty-rubric.md) for
requested-versus-generated difficulty review. It defines assessment conditions,
worked anchors, evidence fields, uncertainty, template variation, and the matching
and agreement protocol to predeclare before held-out judging. Assess the level
independently, then compare it with the requested level to report `matches`,
`too_easy`, `too_hard`, or `uncertain`. Requested labels remain separate from
estimates and learner performance. Difficulty evidence is advisory and cannot
override failed technical checks.

For the original issue 42 reference, use the archived dataset at
`reference_sets/python_tracing/archive/dataset-v0.2.json`. It contains 30 complete,
execution-verified MCQs with human-reviewed categories: 13 easy, 11 medium and
six hard. Each question has one fixed `difficulty` label, four dimension ratings,
a topic and a development/reserved split (18/12). These assignments are frozen;
judge outputs and later model disagreements must never rewrite them.

The human-approved `difficulty` categories and dimension ratings are the
authoritative reference. When evaluating the advisory judge, send only the MCQ
content; keep reference labels, dimensions, reasons and solutions hidden. Count
failed assessments as nonmatches and report valid-only agreement separately.
The dataset remains an AI-assisted, single-human reference, not independent
human agreement or learner calibration. Technical verification is not a human
difficulty label. See [difficulty judging](difficulty-judging.md) for the tool
contract; record evaluation results in the pull request.

## What to report

For issue 44, see the [project report](edcraft%20logs.docx),
Section 6, for relevance checks, model selection and evaluation findings.
The v4 runner freezes all 12 reserved MCQs and seven versioned control contents,
and collects independent Python correctness, explicit requirements and shared
relevance reports. The reference and control files are unchanged.
It neither consumes difficulty reports nor makes generative judge calls.
Difficulty judgments and quality concerns remain in their separate report.
The original v1 live review is retained
as historical evidence. There are no human relevance labels for the reserved set;
similarity does not establish relevance accuracy.
The embedding selection in the log compares published online
benchmarks rather than claiming a new domain evaluation. Model calls remain opt-in.

Run the frozen review with `uv run python scripts/evaluate_code_relevance.py
--env-file .env --output .artifacts/relevance-v4.jsonl`.
The new protocol is `code-relevance-evaluation-v4-shared`. Reports contain
`technical`, `requirements` and `relevance`; embedding details are now under
`relevance.similarity`. The manifest identifies the renderer, shared tool and
review-report versions. Existing evaluation artifacts retain their original schemas.

The former `assess_code_quality` MCP name and the old script name are removed.
For a Python question, prepare shared-tool input with
`domains.code.relevance.relevance_input(question, CodeQuestionRequest(...))` and
call `assess_relevance` with that object as `request`. Call
`check_code_question_correctness(question)` and
`check_code_question_requirements(question, request)` separately when those checks
are needed. For other domains, supply an original author request and complete
textual question representation with rendering provenance and any omissions.
The shared service does not infer or enforce domain requirements. All tools reject
attached difficulty/correctness reports; no check reuses another check's judgment.
The runner continues to reject `--difficulty-reports`.
The runner retains errors and usage, flushes completed records and refuses to
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
This run-success check does not turn similarity into a relevance pass threshold.

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


## Active v0.3 model comparison: GLM5.3 Flash versus Qwen

Versioned requests, raw outcomes, attempts and recovery audits are in the
[portable evidence bundle](../evidence/issue-86/README.md). It also contains the
frozen Qwen baseline needed by the comparison command.
The superseded v0.4 result is summarized in
[evaluation history](evaluation-history.md#difficulty-matrix-v04-soclaas-22-october-2026);
its historical rubric is [archived](archive/difficulty-rubric-v0.4.md).

The user selected v0.3 after the v0.4 experiment did not improve observed overall
agreement. `reference_sets/python_tracing/dataset.json` has been restored byte for
byte from `archive/dataset-v0.3.json`; the superseded v0.4 data is preserved in
`archive/dataset-v0.4.json`. The active reference uses
[difficulty-rubric-v0.3.md](difficulty-rubric-v0.3.md), with 15 easy, 9 medium and
6 hard questions. Production MCP v0.2 contracts remain unchanged.

`scripts/compare_soclaas_difficulty.py` validates the exact dataset/rubric hashes,
messages, schema and prompt versions against the frozen Qwen run before making
any inference request. It uses the original v0.3 response schema and raw model
ratings; it does not use v0.4's derived ratings or stricter evidence validators.
The SoCLaaS catalogue identifies `x-test-1` as **Testing GLM 5.3 Flash**. This is a
serving alias, not an immutable model-weight identifier.

The comparison has two assessments per question, concurrency two, the same
16,384-token output budget and provider-default reasoning/sampling. Client and
judge deadlines are disabled, SDK retries are zero, and transport failures receive
one explicit identical-request retry. Each failed attempt releases its concurrency
slot before retrying; an unrelated pending request does not hold up the retry
phase. Neither transport failures nor unreturned requests count as accuracy
failures. Content/schema failures and abstentions remain nonmatches.

Invoke with `python -m scripts.compare_soclaas_difficulty` and supply
`--env-file`, `--baseline` (original Qwen run directory), `--baseline-records`
(transport-retried Qwen final records), `--catalogue` (fresh saved model catalogue),
`--model x-test-1`, `--expected-display-name 'Testing GLM 5.3 Flash'` and a fresh
`--output` directory. The model identity must match the catalogue display name.

Retain exact requests, source/dataset/rubric snapshots, raw responses, all attempts,
final slot records, predictions CSV, latency/tokens, confusion, dimension scores,
per-class F1, repeat stability, paired gains/losses against Qwen and checksums.
Qwen's existing result is 47/60 (78.3%). Its initial calls used finite deadlines,
while its three retries and the GLM comparison use no local deadlines. This is a
historical model comparison on an inspected reference, not a fresh independently
held-out study or an isolated test of deadline effects.


### GLM transport recovery amendments

Two unreturned calls stalled the initial GLM run. The user explicitly selected
restarting only unfinished requests. `--resume` validates the parent model and
frozen requests, retains every completed non-transport assessment byte for byte
(including incorrect labels, schema failures and abstentions), and schedules only
unreturned/queued or eligible transport-failed slots. Operator interruptions are
recorded separately from transport failures and do not enter accuracy.

A subsequent provider-wide HTTP 503 burst exhausted the original retry budget.
One extra transport retry per failed slot was declared with
`--extra-transport-retries 1` before further inference. HTTP 429/502/503/504
responses trigger 5–60-second availability backoff. This pauses new requests;
it does not impose a deadline on in-flight requests. Request starts are now
logged separately. Every phase preserves its own manifest, requests, attempts,
source snapshots, operator audit and final records. Never retry a completed
assessment just because it disagrees with the reference or exhausts its output
budget. The token budget remains the Qwen baseline's 16,384 throughout.

Report both agreement and classification coverage. Successful-response latency
must exclude immediate service errors: a fast HTTP 503 is not a fast model
assessment. Failed-transport and interrupted-call token usage may be unavailable.
These operational amendments and different service conditions limit causal
claims about model differences.
