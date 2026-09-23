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

## Target workflow evaluation

The [agreed workflow](docs/question-generation/README.md) adds free-form prompts and
model-selected check plans; it is not implemented on this docs branch yet.

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
