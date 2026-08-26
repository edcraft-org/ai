FROM python:3.12-slim AS builder

ARG STEP_TRACER_COMMIT=ab7e22ef18b776a9cbd5260bef4b4eeacc17db11

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir \
        "pydantic==2.13.4" \
        "step-tracer @ git+https://github.com/edcraft-org/step-tracer.git@${STEP_TRACER_COMMIT}"

FROM python:3.12-slim

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
COPY src/edcraft_validator /app/edcraft_validator

WORKDIR /app
USER 65532:65532

ENTRYPOINT ["python", "-m", "edcraft_validator._worker"]

