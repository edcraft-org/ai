# EdCraft AI Question Validator

This prototype validates AI-generated Python return-value MCQs without asking a
second LLM to judge correctness.

## Current flow

1. Parse the AI-generated draft using a strict Pydantic schema.
2. Reject unsupported or risky Python syntax using an AST safety gate.
3. Run EdCraft's `step-tracer` inside a restricted Docker container.
4. Use the traced return value as the authoritative answer.
5. Ask the model to generate distractors using that computed answer.
6. Ensure distractors are unique, type-compatible, and wrong.
7. Return an explainable `valid`, `invalid`, or `execution_error` report.

## Run

```powershell
uv sync
docker build -f docker/Dockerfile -t edcraft-validator-executor:local .
uv run python -m edcraft_validator examples/valid_square.json
uv run pytest
```

To include the real-container integration test:

```powershell
$env:EDCRAFT_RUN_DOCKER_TESTS = "1"
uv run pytest
```

The `examples` directory also contains end-to-end cases for loops and branches,
floating-point calculations, helper-function calls, and structured dictionary
answers. Every `valid_*.json` example is automatically exercised by the test suite.

## Supported scope

- One Python function return-value question per JSON document
- Python code supplied as a readable array of lines or an escaped string
- JSON-compatible inputs and answers
- Basic expressions, assignments, `if`, and `for` loops
- A small allowlist of safe built-in functions
- Exact structured comparison and tolerant numeric comparison

The first version deliberately rejects imports, attributes, classes, recursion,
comprehensions, `while`, file access, networking, and dynamic execution.

## Where EdCraft's tracer is sufficient

It supplies the execution trace, function arguments, return value, loop events,
branch events, and variable snapshots. Reusing it avoids implementing another
Python instrumentation engine.

## Where the tracer is insufficient

- It executes transformed code with in-process `exec()` and is not a sandbox.
- It has no timeout, CPU limit, memory limit, filesystem restriction, or network
  restriction.
- Calls inside lambdas and comprehensions and walrus assignments are not traced.
- Class and instance state tracking is incomplete.
- It does not decide whether an AI answer or distractor is correct.
- It does not check whether natural-language wording matches the code semantics.

## Docker execution boundary

The default executor starts one disposable container per question. It applies:

- no network access;
- a read-only root filesystem;
- 128 MB memory and swap limits;
- half of one CPU and a 64-process limit;
- all Linux capabilities dropped;
- `no-new-privileges` and an unprivileged user;
- 16 MB of temporary storage; and
- an in-container code timeout, plus a separate Docker startup allowance and
  host-enforced cleanup fallback.

If the host fallback is reached, validation reports `CONTAINER_TIMEOUT` rather
than incorrectly attributing Docker startup delay to the generated program.

The image uses a pinned Step Tracer commit. Build the image again when that pinned
version or the worker implementation changes.

## Fake generation pipeline

Before connecting an AI provider, the model-independent generation pipeline can
be exercised using the existing examples:

```powershell
uv run python -m edcraft_validator.generation `
  --topic loops `
  --difficulty intermediate `
  --num-distractors 3
```

Supported topics are `arithmetic`, `conditionals`, `loops`, `functions`, and
`lists`. Difficulties are `beginner`, `intermediate`, and `advanced`. The fake
generator selects a fixed example by topic; difficulty will be used by the future
AI implementation.

The service makes at most three draft generation attempts and up to three
distractor-generation attempts per draft. Invalid drafts are sent back as
feedback for another attempt, while infrastructure or execution errors stop the
run without wasting another generation. Attempts are appended to
`.artifacts/generation_attempts.jsonl`, which is excluded from Git.

## OpenAI generation pipeline

Paste your replacement API key into the local `.env` file. This file is excluded
from Git and must never be committed:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5.6-luna
```

Then generate and deterministically validate one question:

```powershell
uv run python -m edcraft_validator.generation `
  --provider openai `
  --topic loops `
  --difficulty intermediate `
  --num-distractors 3
```

The OpenAI model only generates candidates. The existing AST safety checks,
Docker execution, answer comparison, and retry rules remain responsible for
validation.

## Reproducibility

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for pinned dependencies, environment setup, and verification commands.
