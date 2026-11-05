FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# uv.lock pins step-tracer from git; the slim base has no git client.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The project build needs the readme and the packaged rubric.
COPY pyproject.toml uv.lock README.md ./
COPY docs/difficulty-rubric.md ./docs/difficulty-rubric.md
COPY src ./src

RUN uv sync --frozen --no-dev

RUN groupadd --system --gid 10001 worker \
    && useradd --system --uid 10001 --gid worker --home-dir /app \
        --no-create-home --shell /usr/sbin/nologin worker \
    && chown -R worker:worker /app

USER worker

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["python", "-m", "edcraft_validator.worker"]
