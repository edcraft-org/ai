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
current workflow. Structured output defaults to `json_object` with local schema
validation; `json_schema` remains an explicit opt-in for endpoints that support
strict structured outputs.

### Mathematics authoring baseline

```bash
SOCLAAS_MAX_RETRIES=0 uv run python scripts/evaluate_authoring_loop.py \
  --env-file .env --domain math --provider soclaas --model x-test-2 \
  --set all --jobs 12 --output .artifacts/math-authoring.jsonl
```

Set the provider's SDK retry count to zero for a controlled run, for example
`SOCLAAS_MAX_RETRIES=0` or `OPENAI_MAX_RETRIES=0`. The manifest records the
observed provider settings, so check the retry count there as well.

The fixed mathematics set has eight natural prompts and four unsupported prompts.
Natural prompts cover a linear equation, a monic quadratic to factorise, two
binomials to expand, a cubic derivative, a 2 by 2 determinant, a rational
expression to simplify, an arithmetic expression and a short prose word problem.
Unsupported prompts ask for a proof, 3 by 3 eigenvalues, a limit and a probability
word problem. Unsupported requests may be reshaped or may fail. Use
`--set natural`, `--set unsupported` or `--set all`. `--jobs N` cycles through the
selected set.

Each JSONL record keeps the final status, attempts, failed check codes for every
attempt, the checked, needs_review, failed and unresolved flags, requested and
estimated difficulty with its decision path, relevance score, threshold and
decision, checked examples, declared domain size, author and judge tokens and wall
time. Unknown token counts are null. Checked jobs also save the reusable artifact
and deterministic previews at seeds 0, 1 and 42. The runner replays each preview
twice from the saved artifact without model or MCP calls and asserts that the
results match.

The summary reports counts by outcome and set, first-attempt and overall checked
yield with every requested job in the denominator, revision counts, the failure
taxonomy by check code, relevance flags for the unsupported set, a requested
against estimated difficulty table, median and maximum latency and author, judge
and combined token totals. The manifest keeps the exact validator revision,
provider, resolved model, provider settings, prompt versions and rubric versions.

These results describe one model on a fixed prompt set. They are not a general
accuracy estimate. Difficulty agreement is measured against the provisional
`math-ir-v0.1` rubric and remains advisory.

## Mathematics correctness

```bash
uv run python scripts/evaluate_math_correctness.py > .artifacts/math-correctness.json
```

The script runs fixed concrete examples across the public worker boundary and one
sampled qualification campaign, then prints a JSON record to stdout. There is no
measurement flag, and the command succeeds even when an example's observed outcome
differs from its expectation; inspect `matched_examples` and each example's
`matches` field instead. The examples are regression fixtures, not an accuracy
benchmark. `qualification` reports seeded property-based observations over sampled
parameter assignments, not an exhaustive Cartesian enumeration; a passing campaign
supports only the observed samples. Keep request/result records for regression
comparison, and separate correctness evidence from relevance or difficulty claims.

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
