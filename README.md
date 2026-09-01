# EdCraft AI Question Validator

This prototype validates AI-generated Python execution-trace MCQs without asking
a second LLM to judge correctness.

## Current flow

1. Parse the AI-generated draft using a strict Pydantic schema.
2. Reject unsupported or risky Python syntax using an AST safety gate.
3. Run EdCraft's `step-tracer` inside a restricted Docker container.
4. Use the selected traced fact as the authoritative answer.
5. Keep the model-generated distractors and misconception metadata with the
   generation attempt, while excluding the metadata from the final question.
6. Ensure distractors are unique, type-compatible, and wrong.
7. Return an explainable `valid`, `invalid`, or `execution_error` report.

## Run

```bash
uv sync
docker build -f docker/Dockerfile -t edcraft-validator-executor:local .
uv run python -m edcraft_validator examples/valid_square.json
uv run pytest
```

The `examples` directory also contains end-to-end cases for loops and branches,
floating-point calculations, helper-function calls, and structured dictionary
answers. Every `valid_*.json` example is automatically exercised by the test suite.

## Supported scope

- One Python function execution-trace question per JSON document
- Python code supplied as a readable array of lines or an escaped string
- JSON-compatible inputs and answers
- Basic expressions, assignments, `if`, and `for` loops
- A small allowlist of safe built-in functions
- Exact structured comparison and tolerant numeric comparison

`answer_target` selects the authoritative traced fact. Supported targets are:

- `return_value`: the entry function's return value;
- `loop_iterations`: total loop-body iterations across all loops;
- `loop_executions`: number of loop statements encountered;
- `branch_executions`: number of evaluated `if` conditions; and
- `function_calls`: all traced calls, including the entry function and safe
  built-ins.

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

The default executor starts one disposable container per direct question. During
template approval, every parameter combination is sent to one disposable
container as a batch. It applies:

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
  --provider fake `
  --topic loops `
  --difficulty intermediate `
  --num-distractors 3
```

Supported topics are `arithmetic`, `conditionals`, `loops`, `functions`, and
`lists`. Difficulties are `beginner`, `intermediate`, and `advanced`. The fake
generator selects a fixed example by topic; difficulty will be used by the future
AI implementation.

The service makes at most three complete generation attempts. Invalid drafts are
sent back as feedback for another attempt, while infrastructure or execution
errors stop the run without wasting another generation. Misconception reasons
are retained in attempt logs but are not part of the final question payload.
Attempts are appended to
`.artifacts/generation_attempts.jsonl`, which is excluded from Git.

## Generation observability

Each attempt log record includes the provider, model, generation and validation
durations, outcome status, and validation issue codes. The service also keeps
process-local counters for attempts, outcomes, provider requests, issue codes,
and total stage durations. Prompts and API credentials are not added to
telemetry.

## Provider architecture

The generation service depends on the model-independent `QuestionGenerator`
protocol. Provider adapters handle communication and provider-specific response
decoding; the code domain owns the Python prompt and candidate schema in
`domains/code/generation.py`. The deterministic validator then computes the
answer and decides whether to accept or retry the candidate. Provider failures
are recorded as retryable attempts with timing and issue codes.

The application layer in `application/generate_question.py` owns dependency
wiring. The CLI and future frontends call that application service instead of
constructing providers and validators themselves. The CLI constructs adapters
through the provider registry. To add a model, implement `generate_draft` and
provider metadata, register the factory in `generation/registry.py`, and add
adapter tests. The CLI routing code does not need to change.

## Validation architecture and future domains

Generated provider output is represented as an untrusted `QuestionCandidate`.
It is promoted to a `GeneratedQuestion` only after the validation pipeline has
computed the authoritative answer. Domain-specific code now lives under
`edcraft_validator/domains`:

```text
domains/
  code/
    generation.py
    pipeline.py
    tools.py
  math/       # future
  physics/    # future
```

The current code-domain pipeline is composed of focused tools:

```text
QuestionCandidate
  -> static_safety
  -> python_execution (Docker + Step Tracer)
  -> distractor_consistency
  -> question_wording
  -> ValidationRun / ValidationReport
```

Each tool returns a `ToolResult` containing its status, issues, facts, and
duration. The pipeline aggregates those results into a `ValidationRun`; the
existing `QuestionValidator` is a small compatibility facade that converts the
run into the original `ValidationReport` shape. Tool evidence is available in
`ValidationReport.tool_results`.

When another domain is added, give it its own module with a candidate schema,
focused tools, and pipeline. For example, a future math module could contain
SymPy and Lean adapters, while a physics module could contain unit,
dimensional-analysis, and numerical-solver adapters. These modules should not
be added to the Python pipeline. A domain registry or validation profiles can be
introduced when there are at least two real domain pipelines. Both the CLI and
a future HTTP frontend should call an application service rather than importing
provider or tool implementations directly.

## OpenAI generation pipeline

Paste your replacement API key into the local `.env` file. This file is excluded
from Git and must never be committed:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5-mini
```

Select the provider explicitly with `--provider`; provider selection is not read
from `.env`.

Generate and deterministically validate one question with OpenAI:

```bash
cd ai
uv run python -m edcraft_validator.generation \
  --provider openai \
  --topic loops \
  --difficulty intermediate \
  --num-distractors 3
```

```bash
uv run python -m edcraft_validator.generation --provider openai --topic loops --difficulty intermediate --num-distractors 3
```

The command prints the generated question as JSON. To save and inspect it:

```bash
uv run python -m edcraft_validator.generation --provider openai --topic loops --difficulty intermediate --num-distractors 3 --no-log > /tmp/openai-question.json
jq . /tmp/openai-question.json
```

Ollama uses the same model-independent request and validation pipeline. Start
Ollama, make sure the configured model is available, then run:

```bash
ollama pull qwen2.5-coder:14b
export OLLAMA_TIMEOUT_SECONDS=300
export OLLAMA_TEMPERATURE=0.2
/usr/bin/time -p uv run python -m edcraft_validator.generation --provider ollama --topic loops --difficulty intermediate --num-distractors 3 --no-log > /tmp/ollama-question.json
jq . /tmp/ollama-question.json
```

Ollama receives a deliberately simple, non-recursive wire schema: `inputs` is a
JSON object and `distractors` is a JSON array. The shared adapter converts this
response into the tagged domain model and performs strict local validation. The
`time -p` wrapper records the rough wall-clock cost, including failed or timed-out
runs.

OpenAI uses strict Structured Outputs with the tagged domain schema. This keeps
schema adherence at the API boundary while allowing Ollama to use a smaller,
more reliable schema for local constrained decoding.

Provider selection is always explicit through `--provider`; it is not inferred
from the environment. `OPENAI_MODEL`, `OLLAMA_MODEL`, and `SOCLAAS_MODEL` only
select the model for the explicitly selected provider.

## Tests

Run the fast suite without requiring Docker:

```bash
uv run pytest -m "not docker"
```

Run the focused provider tests:

```bash
uv run pytest tests/test_ollama_generator.py -q
```

OpenAI provider tests use mocked clients and run in the normal test suite. The
real API test is opt-in and should be run before a PR:

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run pytest -m openai_live -q
```

The pull-request CI workflow runs the real API test for pull requests from the
main repository using the `OPENAI_API_KEY` GitHub Actions secret. Forked pull
requests do not receive this secret and therefore skip that live-test job.

Run the complete suite, including Docker integration tests, after starting the
Docker daemon:

```bash
uv run pytest
```

Formatting and lint checks:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
```

In the direct workflow, the OpenAI model only generates candidates. The existing
AST safety checks, Docker execution, answer comparison, and retry rules remain
responsible for validation.

## Reusable template generation

The lower-cost workflow asks OpenAI, Ollama, or another registered provider to
author one reusable template. The template declares a small finite set of integer
values, a Python program, an answer target, an equivalent answer expression, and
deterministic distractor recipes. Template approval executes every possible
parameter combination in one Docker container and rejects the whole template if
any answer or distractor is invalid.

After approval, question generation makes no AI, Docker, or validation call. It
checks the template hash, selects parameter values deterministically from the
seed, evaluates the restricted expressions, and renders the question. The output
records the template ID, version, hash, seed, and selected parameters.

Validate the included raw example once:

```bash
uv run python -m edcraft_validator.template validate \
  examples/templates/arithmetic_linear.json \
  --output /tmp/approved-arithmetic-template.json
```

Validate and generate a loop-iteration question:

```bash
uv run python -m edcraft_validator.template validate \
  examples/templates/loop_iterations.json \
  --output /tmp/approved-loop-template.json

uv run python -m edcraft_validator.template generate \
  /tmp/approved-loop-template.json --seed 42
```

Generate any number of reproducible questions locally from the approved file:

```bash
uv run python -m edcraft_validator.template generate \
  /tmp/approved-arithmetic-template.json --seed 42

uv run python -m edcraft_validator.template generate \
  /tmp/approved-arithmetic-template.json --seed 43
```

Author and approve a new template with exactly one provider call:

```bash
uv run python -m edcraft_validator.template author \
  --provider openai \
  --topic arithmetic \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/approved-openai-template.json
```

Use `--provider ollama` to author through Ollama with the same template contract.
Docker is required for `author` and `validate`, but not for `generate`.

The initial topic-to-answer mapping is deterministic: arithmetic and lists ask
for `return_value`, loops ask for `loop_iterations`, conditionals ask for
`branch_executions`, and functions ask for `function_calls`. This keeps the human
input limited to topic and difficulty while still producing different execution-
trace question types.

The intentionally small first version supports one to three integer parameters,
two to four values per parameter, and at most 64 total combinations. Answer and
distractor expressions support arithmetic, comparisons, boolean operators, and
conditional expressions without function calls. Arbitrary model-generated input
generator programs are not executed.

## Reproducibility

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for pinned dependencies, environment setup, and verification commands.
