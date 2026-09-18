# Reproducibility

- Requires Python 3.12 or newer.
- Dependencies are resolved with `uv` and locked in `uv.lock`.
- `step-tracer` is pinned to commit `ab7e22ef18b776a9cbd5260bef4b4eeacc17db11`.
- Copy `.env.example` to `.env` for local configuration. Never commit secrets.
- Keep generated evaluation output under `.artifacts/`; it is ignored by Git.

## Standard verification

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

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
