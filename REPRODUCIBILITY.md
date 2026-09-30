# Reproducibility

- Requires Python 3.12 or newer.
- Dependencies are resolved with `uv` and locked in `uv.lock`.
- `step-tracer` is pinned to commit `ab7e22ef18b776a9cbd5260bef4b4eeacc17db11`.
- Copy `.env.example` to `.env` for local configuration. Never commit secrets.
- Keep generated evaluation output under `.artifacts/`; it is ignored by Git.

The readable-layout refactor changes internal Python module paths only. It does not
change CLI commands, flags, environment variables, locked dependencies, or serialized
template and question artifacts. Scripts that import implementation modules directly
must use the new paths documented in [README.md](README.md#architecture).

## Standard verification

```bash
uv lock --check
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Live provider verification

Load local configuration explicitly for the opt-in OpenAI pytest:

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run --env-file .env pytest -m openai_live -q
```

To verify the same response contract through another provider, run one complete
authoring attempt (the CLI loads `.env`):

```bash
uv run python -m edcraft_validator.cli evaluate \
  --domain code --provider ollama \
  --topic arithmetic --difficulty beginner --repetitions 1 \
  --output .artifacts/ollama-compatibility.jsonl
```

Repeat with `--provider soclaas` and a distinct output path when its endpoint is
available. Mocked adapter tests verify request/schema/parser wiring; only a live run
verifies endpoint compatibility. Inspect the recorded failure stage and code to
distinguish transport failures, malformed responses, and rejected model proposals.

## Model-directed workflow evaluation

The [workflow](docs/question-generation/README.md) implements free-form prompts,
model-selected checks, application-owned candidate injection, and three-attempt
correction. Durable approval remains a separate integration.

Run the small real-provider set (three difficulties) and an explicitly labelled
correction drill. The drill replaces the first real proposal's answer expression
with `(original_expression) + 1`, then uses real model calls and MCP evidence for correction. It is
not an unbiased model-quality measurement.

```bash
uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini \
  --output .artifacts/authoring-natural.jsonl
uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini --correction-drill \
  --output .artifacts/authoring-correction.jsonl
```

For each future evaluation attempt, retain the original prompt, domain, exact model
and provider settings, prompt/response-schema versions, allowed capability catalogue
and versions, selected checks/arguments, resolved prerequisites, candidate/artifact
hashes, actual MCP results and scope, final acceptance and timings. Keep source hashes
when retrieval is used, and approval bound to the exact artifact when review is added.
Do not log credentials or hidden model reasoning.

Use a labelled prompt set spanning supported novel concepts, ambiguous requests,
unsupported capabilities, and valid/invalid templates. Measure selection omissions,
unnecessary checks, invalid arguments, false acceptance/rejection, latency and cost
separately from JSON/schema validity. Run the same cases and acceptance rules across
providers; identify the exact Qwen/LFM model tag and runtime version for local runs.

Test the planner with recorded catalogues and the validator with saved plans/results;
then run live end-to-end evaluations through the MCP server and each supported model.
Changing the candidate requires new evidence. Replaying generation is not guaranteed
to reproduce model output, but stored artifacts and seeds must reproduce questions.


## Existing-candidate MCP validation

`validate` now requires a provider and returns a result envelope. It uses one
model-selected checking attempt on the exact supplied candidate, without revisions:

```bash
uv run --env-file .env python -m edcraft_validator.cli validate \
  --domain code --provider openai --model gpt-5-mini \
  examples/templates/arithmetic_linear.json \
  --output .artifacts/existing-candidate-result.json
```

Exit 0 means a reusable artifact is present; exit 2 preserves unsuccessful checking
results. Extract `artifact` for seeded generation. Candidate validation and authoring
both use MCP; the old pipeline and silent answer/distractor repair are removed.
Successful checks assign a new artifact ID and save the final proposal, plan, catalogue,
per-attempt evidence, request, and non-secret provider settings. JSON serialization
preserves this ID. Code question instances carry the artifact ID and seed for later
replay; previews use the same local generator as subsequent questions. No model/MCP
work occurs during finalization or replay. The final evidence acknowledgement remains
part of checking. Independent checking jobs receive different IDs even when their
proposals match; the existing template ID still controls seeded input selection.

Human approval and revision enforcement are deferred to Issue 40. No defenses against
direct internal-record editing or migrations of old development data are provided.
Regenerate artifacts that fail the new provenance schema; reset development storage
when integrating that schema into the full workflow.
