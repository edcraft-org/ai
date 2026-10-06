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

Evaluation is the next step in [issue 40](https://github.com/edcraft-org/ai/issues/40).
The following script runs three prompts, one for each difficulty:

```bash
uv run python scripts/evaluate_authoring_loop.py --env-file .env \
  --provider openai --model gpt-5-mini \
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
Repeat the same cases with Ollama and its configured model. SocLaas is currently
unused, so its live verification is deferred.

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

Use the same reviewed cases across active providers. Include successful requests,
repairable and repeated failures, unsuitable check plans, invalid arguments,
unsupported requests, and incomplete conversations.

Record the provider/model and non-secret settings, request, selected checks, attempt
history, results, and timings. For successful runs, retain the saved artifact and
preview seeds. Report selection mistakes, correction success, false
acceptance/rejection, and latency separately from schema or tool-call failures.
The smoke scripts need additional reviewed cases to complete this evaluation.

See the [workflow guide](question-generation/README.md#saving-editing-and-reuse)
for saving and replaying questions, and [earlier evaluation results](evaluation-history.md)
for historical evidence.
