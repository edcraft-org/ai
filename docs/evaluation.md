# Evaluation

Run from the repository root. Keep credentials in `.env` and generated records in
ignored `.artifacts/`. Preserve exact source revisions, settings, prompt/rubric
versions, requests and failures. A passing smoke verifies compatibility for its
examples; it does not establish accuracy, educational quality or learner difficulty.

## Checks before a PR

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest

RUN_OPENAI_LIVE_TESTS=1 uv run --env-file .env pytest -m openai_live -q
RUN_RELEVANCE_LIVE_TESTS=1 uv run --env-file .env pytest -m relevance_live -q
```

The OpenAI test authors, saves, replays, edits, rechecks and expands a template.
The relevance test exercises the configured hosted decision service. Both require
credentials; neither is an accuracy benchmark. Same-repository PRs also run an
OpenAI template evaluation in CI and upload its JSONL result. Ollama's opt-in
workflow test uses `RUN_OLLAMA_LIVE_TESTS=1` and requires a running local server.

## Authoring and reuse

```bash
uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini --jobs 5 \
  --output .artifacts/authoring-natural.jsonl

uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini --correction-drill \
  --output .artifacts/authoring-correction.jsonl
```

The natural prompts cover addition, conditionals, loop accumulation, list summation
and a helper inside a loop. The correction drill deliberately supplies a wrong
answer first; report it separately. Additional jobs cycle through the fixed cases.
Use a common model/request/schema/checking budget for a controlled comparison.

The runner records each completed `authoring_result`, flushes JSONL after each job,
and writes manifest and summary files. It saves full catalogue snapshots, reusable
artifacts and deterministic previews at seeds 0, 1 and 42. Reopening those artifacts
and replaying previews must require no model or MCP calls. Keep unsuccessful jobs
in the denominator; unfinished requested jobs remain unresolved.

Report first-attempt and overall usable yield, correction outcomes, canonical
answer/distractor failures, schema/tool failures and request drift. Report related
questions sharing a template as clustered observations, not independent evidence.
State finite-domain/distinct-output limits for reuse comparisons.

Author generation/revision usage is separate from judge usage inside check
evidence. Retain every application call and attempt; SDK HTTP retries are not
additional application call records. Use zero SDK retries for controlled runs.
Unknown token totals are null, not zero; reported partial totals remain useful.
Separate production calls from offline evaluation calls and latency.

The current revision policy is `full-candidate-v1`: each correction returns the
complete proposal and rechecks it under the frozen check plan. Current correctness
checks use bounded Hypothesis samples, not exhaustive domain enumeration. Earlier
native-tool/acknowledgement, patch-only or exhaustive-checking experiments describe
their recorded revisions. Preserve those records rather than pooling them with the
current workflow. SocLaas structured output defaults to `json_schema`;
`json_object` is an explicit weaker wire option with local schema validation.

## Difficulty and relevance

The production [v0.2 rubric](difficulty-rubric.md) and offline
[v0.3 rubric](difficulty-rubric-v0.3.md) have different assessment conditions.
The reference set contains 30 concrete questions: 15 easy, 9 medium and 6 hard.
Keep requested levels and generator identity hidden from independent raters/judges.
Freeze human ratings and uncertainty before revealing model judgments. See the
[reference README](../reference_sets/python_tracing/README.md) for provenance.

The earlier cascade experiment used concrete questions, v0.3, `x-test-3` decisions
and `x-test-1` reasoning. The current authoring cascade assesses templates using
production v0.2 and the same configured model for both stages. Its 0.70 token gate
and the reasoning judge's 0.80 self-confidence gate are provisional. The prior
experiment is not accuracy evidence for this new combination. Freeze and evaluate
the deployed model, rubric, prompt and thresholds together before making new claims.
Do not change rubric semantics during a structural refactor.

Relevance uses the same configured judge model with reasoning disabled. The default
cutoff (0.9223792980579683) was fitted on 92 development pairs for `x-test-3`.
Decision scores are normalized yes/no token mass, not calibrated probabilities.
A different model requires checking/recalibrating its cutoff. Technical correctness,
requirement compliance, relevance and difficulty remain independent assessments.

```bash
uv run python scripts/evaluate_code_relevance.py --env-file .env \
  --output .artifacts/relevance-v6.jsonl
```

Protocol `code-relevance-evaluation-v6-configured-decision` reviews 12 reserved
Python questions and seven controls. It collects independent `technical`,
`requirements` and `relevance` reports, with no reasoning/difficulty calls or reused
judgments. It freezes inputs/settings, reserves its output files exclusively,
flushes results and preserves errors. A conflict must not overwrite prior evidence.
The command exits 2 for incomplete measurements, protocol failures or unexpected
mandatory-check results. Expected wrong-answer or missing-requirement controls do
not make a run fail. The reserved set has no human relevance labels, so completed
measurements alone do not establish relevance accuracy.

Inspect agreement/confusion, false acceptance/rejection, unresolved outcomes and
representative disagreements on labelled data. Embedding similarity and older local
Qwen results are historical baselines; do not compare different prompt/cutoff or
serving configurations as if they were identical. Treat relevance and plausibility
judgments as advisory and state sample size, dataset reuse and uncertainty.

[Historical results](evaluation-history.md) retain the older baseline and GLM/Qwen
comparison. Store new experimental protocol versions with their run manifests and
raw data. Routine refactor descriptions and test counts belong in PRs.
