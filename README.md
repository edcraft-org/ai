# EdCraft AI Question Templates

EdCraft uses an AI model once to author a reusable Python question template. It
then validates the template's complete finite input domain and generates concrete
questions deterministically without further AI calls.

Direct AI-to-question generation is intentionally not supported. This keeps API
cost proportional to the number of templates rather than the number of questions.

## Current workflow

```text
topic + difficulty + provider
  -> AI proposes code, parameters, answer logic, and distractor candidates
  -> application derives identity, target, wording, version, and question type
  -> AST safety checks
  -> all parameter combinations run in one Docker batch
  -> globally valid distractor recipes selected from the candidates
  -> answers and selected distractors checked for every combination
  -> approved template + validation hash
  -> deterministic questions generated locally from seeds
```

Template authoring makes one provider request, including extra distractor candidates.
Template approval uses Docker once.
Generating a question from an approved template uses no AI, Docker, or per-question
validation call.

## Setup

```bash
uv sync
docker build -f docker/Dockerfile -t edcraft-validator-executor:local .
```

Configure only the provider you intend to select:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5-mini

OLLAMA_MODEL=qwen2.5-coder:14b
OLLAMA_TIMEOUT_SECONDS=300
OLLAMA_TEMPERATURE=0
```

Provider selection is always explicit through `--provider`.
Model selection can also be explicit through `--model`; when it is omitted, the
selected provider's environment setting is used.

## Author and approve a template

OpenAI uses strict Structured Outputs:

```bash
uv run python -m edcraft_validator.template author \
  --provider openai \
  --model gpt-5-mini \
  --topic arithmetic \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/approved-template.json
```

Ollama uses its native structured endpoint with a simple provider-specific wire
schema. The adapter strictly normalizes that response into the same local proposal
contract used by OpenAI:

```bash
/usr/bin/time -p uv run python -m edcraft_validator.template author \
  --provider ollama \
  --model qwen2.5-coder:14b \
  --topic loops \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/approved-loop-template.json
```

SocLaas is also registered through its OpenAI-compatible endpoint. Configure
`SOCLAAS_API_KEY`, `SOCLAAS_BASE_URL`, and `SOCLAAS_MODEL`, then select
`--provider soclaas`.

## Validate an existing raw template

The repository includes examples for integers, booleans, strings, and integer
lists:

```bash
uv run python -m edcraft_validator.template validate \
  examples/templates/arithmetic_linear.json \
  --output /tmp/approved-arithmetic-template.json

uv run python -m edcraft_validator.template validate \
  examples/templates/loop_iterations.json \
  --output /tmp/approved-loop-template.json

uv run python -m edcraft_validator.template validate \
  examples/templates/conditional_boolean.json \
  --output /tmp/approved-boolean-template.json

uv run python -m edcraft_validator.template validate \
  examples/templates/conditional_string.json \
  --output /tmp/approved-string-template.json

uv run python -m edcraft_validator.template validate \
  examples/templates/list_sum.json \
  --output /tmp/approved-list-template.json
```

Approval checks every value in the template's Cartesian product. All cases are
sent to one disposable Docker container to avoid repeated startup costs.
Rejected templates raise structured diagnostics with a stable code, relevant
field, and failing parameter values when available; messages remain human-readable.

## Generate concrete questions locally

The same seed and approved template always produce the same output:

```bash
uv run python -m edcraft_validator.template generate \
  /tmp/approved-arithmetic-template.json --seed 42

uv run python -m edcraft_validator.template generate \
  /tmp/approved-arithmetic-template.json --seed 43
```

Each output records the template ID, version, SHA-256 hash, seed, selected
parameters, code, question, answer target, answer, and distractors.
Rendered misconception reasons are preserved alongside their selected distractors.

## Currently supported

- Domain: Python code execution-trace MCQs.
- Providers: OpenAI, Ollama, and SocLaas.
- Topic selections: `arithmetic`, `conditionals`, `loops`, `functions`, and
  `lists`.
- Difficulties: `beginner`, `intermediate`, and `advanced`, each with a distinct
  validator-backed authoring profile per topic.
- Template parameters: one to three explicitly typed finite parameters. Supported
  kinds are integers, booleans, bounded printable strings, and bounded integer
  lists. Each parameter has two to four unique values.
- Exhaustive approval: at most 64 total parameter combinations.
- Answers: restricted arithmetic, comparisons, boolean operators, conditional
  expressions, list literals, indexing, and the allowlisted functions `len`, `sum`,
  `min`, `max`, `sorted`, `all`, and `any`.
- Expression safety: at most 500 source characters and 100 syntax nodes; numeric
  intermediates are bounded to magnitude 1 billion, individual sequences to 100
  items, and complete nested values to a cumulative logical size of 1,000.
- Distractors: the provider proposes up to two extra candidates in the same call.
  The finite-domain validator retains the requested two or three deterministic,
  globally unique expressions, each with a misconception reason template.
- Reproducibility: deterministic seed selection and template tamper detection.
  AI-approved artifacts also record the resolved provider and model, authoring
  request, prompt version and SHA-256 hash, generation time, validation time, and
  approval status. API keys and other secrets are never stored.

Topic currently selects the answer target as follows:

| Topic | Answer target |
| --- | --- |
| `arithmetic` | Entry-function return value |
| `conditionals` | Number of evaluated `if` conditions |
| `loops` | Total loop-body iterations |
| `functions` | Traced function calls, including the entry call and safe built-ins |
| `lists` | Entry-function return value |

The execution tracer can also represent `loop_executions`, the number of loop
statements encountered, although the current topic mapping uses total iterations
for loop templates.

### Code-domain coverage matrix

The repository contains one exhaustively validated template for every supported
topic and difficulty pair (15 total):

| Topic | Beginner | Intermediate | Advanced |
| --- | --- | --- | --- |
| Arithmetic | Short integer expression | Boolean adjustment | List aggregate with string mode |
| Conditionals | Boolean branch | Sequential string branches | Nested branches and early returns |
| Loops | One range loop | Sequential loops | Nested loops |
| Functions | One helper | Helper inside a loop | Nested helpers inside a loop |
| Lists | Aggregate | Sorting | Indexing and aggregate arithmetic |

The test suite fails if any topic/difficulty pair is missing or duplicated. Every
template is checked against all finite parameter combinations with the real tracer,
and the Docker integration suite repeats the same matrix across the sandbox boundary.

Supported generated Python includes basic expressions, assignments, `if`, bounded
`for` loops, helper functions, and a small allowlist of safe built-ins. The safety
gate rejects imports, attributes, classes, decorators, recursion, comprehensions,
`while`, file access, networking, and dynamic execution.

## Validation boundary

Docker execution applies no network access, a read-only root filesystem, memory
and CPU limits, dropped Linux capabilities, `no-new-privileges`, an unprivileged
user, host/in-container timeouts, and a 100,000 user-code trace-event limit. The
event limit stops trace data growth deterministically before the container reaches
its memory ceiling. EdCraft's pinned `step-tracer` supplies return values and
execution counts; it is not treated as a sandbox outside this Docker boundary.

The standalone concrete-question validator remains available for debugging,
examples, and future validation tools:

```bash
uv run python -m edcraft_validator examples/valid_square.json
```

It is not part of normal template-based question expansion.

## Architecture

```text
application/__init__.py            stable frontend-facing application facade
domains/code/application.py        code authoring, approval, and expansion use cases
domains/code/evaluation.py         real-provider code-template evaluation
domains/code/templates.py          code template schema, prompt, approval, expansion
domains/code/capabilities.py       supported profiles and their machine-readable rules
generation/base.py                 provider-neutral template protocol
generation/registry.py             explicit provider selection and extension point
generation/openai.py               OpenAI and SocLaas adapters
generation/ollama.py               Ollama adapter
executor.py + _worker.py            batched Docker execution
domains/code/pipeline.py           standalone concrete-question validation pipeline
```

To use another model from an existing provider, pass `--model`; no domain code
changes are required. To add another provider, implement
`QuestionTemplateGenerator.generate_proposal`, register its factory with
`register_template_provider`, and add an adapter test. The application and CLI do
not need provider-specific branches.

Future math and physics domains should have their own template schema, approval
tools, and instance generator under `domains/`. SymPy or Lean should not be added
to the Python-specific pipeline.

## Tests

Mocked provider tests run by default and make no paid API calls:

```bash
uv run pytest -m "not docker"
uv run ruff check .
uv run ruff format --check .
```

Run all tests, including Docker integration:

```bash
uv run pytest
```

Run only the complete code-template matrix locally:

```bash
uv run pytest tests/test_templates.py -q
```

The real OpenAI template-authoring test is opt-in locally and performs full Docker
approval. Build the executor image first. For same-repository pull requests, CI
runs the equivalent evaluation command, fails clearly if the `OPENAI_API_KEY`
secret is missing, and uploads the JSONL attempt record:

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run pytest -m openai_live -q
```

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for pinned dependencies and
environment details.

## Evaluate a real provider

The evaluation command runs the complete authoring and Docker approval workflow,
writes one JSONL record per attempt (including successful approved templates), and
prints pass rate, failure codes, and latency grouped by provider, resolved model,
topic, and difficulty:

```bash
uv run python -m edcraft_validator.template evaluate \
  --provider ollama \
  --model qwen2.5-coder:14b \
  --topic arithmetic \
  --difficulty beginner \
  --repetitions 5 \
  --output .artifacts/ollama-arithmetic-beginner.jsonl
```

Use `--topic all --difficulty all` for the complete 15-profile matrix. Each
repetition makes one real provider call per selected profile, so review the call
count before running a paid provider. The JSONL artifact and summary are written
even when attempts fail; the command exits non-zero if any attempt fails.
