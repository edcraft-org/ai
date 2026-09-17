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
