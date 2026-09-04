# Reproducibility

- Requires Python 3.12 or newer and Docker.
- Dependencies are resolved with `uv` and locked in `uv.lock`.
- `step-tracer` is pinned to commit `ab7e22ef18b776a9cbd5260bef4b4eeacc17db11`.
- The executor image pins the same `step-tracer` commit and Python 3.12 base image family.
- Copy `.env.example` to `.env` for local configuration. Never commit secrets.
- Keep generated evaluation output under `.artifacts/`; it is ignored by Git.

## Standard verification

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For Docker-backed tests:

```bash
docker build -f docker/Dockerfile -t edcraft-validator-executor:local .
uv run pytest -m docker
```
