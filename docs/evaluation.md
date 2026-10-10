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

## What to report

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
