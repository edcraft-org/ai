# EdCraft AI Question Templates

EdCraft uses an AI model once to author a reusable Python question template. It
then validates the template's complete finite input domain and generates concrete
questions deterministically without further AI calls.

Direct AI-to-question generation is intentionally not supported. This keeps API
cost proportional to the number of templates rather than the number of questions.

## Current workflow

```text
topic + difficulty + provider
  -> AI authors one finite template
  -> AST safety checks
  -> all parameter combinations run in one Docker batch
  -> answers and distractor recipes checked for every combination
  -> approved template + validation hash
  -> deterministic questions generated locally from seeds
```

Template authoring makes one provider request. Template approval uses Docker once.
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
OLLAMA_TEMPERATURE=0.2
```

Provider selection is always explicit through `--provider`.

## Author and approve a template

OpenAI uses strict Structured Outputs:

```bash
uv run python -m edcraft_validator.template author \
  --provider openai \
  --topic arithmetic \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/approved-template.json
```

Ollama uses its native structured schema endpoint and the same local template
contract:

```bash
/usr/bin/time -p uv run python -m edcraft_validator.template author \
  --provider ollama \
  --topic loops \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/approved-loop-template.json
```

SocLaas is also registered through its OpenAI-compatible endpoint. Configure
`SOCLAAS_API_KEY`, `SOCLAAS_BASE_URL`, and `SOCLAAS_MODEL`, then select
`--provider soclaas`.

## Validate an existing raw template

The repository includes arithmetic and loop examples:

```bash
uv run python -m edcraft_validator.template validate \
  examples/templates/arithmetic_linear.json \
  --output /tmp/approved-arithmetic-template.json

uv run python -m edcraft_validator.template validate \
  examples/templates/loop_iterations.json \
  --output /tmp/approved-loop-template.json
```

Approval checks every value in the template's Cartesian product. All cases are
sent to one disposable Docker container to avoid repeated startup costs.

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

## Currently supported

- Domain: Python code execution-trace MCQs.
- Providers: OpenAI, Ollama, and SocLaas.
- Topic selections: `arithmetic`, `conditionals`, `loops`, `functions`, and
  `lists`.
- Difficulties: `beginner`, `intermediate`, and `advanced` as authoring guidance.
- Template parameters: one to three integer parameters, each with two to four
  unique values from -100 to 100.
- Exhaustive approval: at most 64 total parameter combinations.
- Answers: restricted arithmetic, comparisons, boolean operators, and conditional
  expressions without function calls.
- Distractors: two or three deterministic expressions, each with a misconception
  reason template.
- Reproducibility: deterministic seed selection and template tamper detection.

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

Supported generated Python includes basic expressions, assignments, `if`, bounded
`for` loops, helper functions, and a small allowlist of safe built-ins. The safety
gate rejects imports, attributes, classes, decorators, recursion, comprehensions,
`while`, file access, networking, and dynamic execution.

## Validation boundary

Docker execution applies no network access, a read-only root filesystem, memory
and CPU limits, dropped Linux capabilities, `no-new-privileges`, an unprivileged
user, and host/in-container timeouts. EdCraft's pinned `step-tracer` supplies return
values and execution counts; it is not treated as a sandbox outside this Docker
boundary.

The standalone concrete-question validator remains available for debugging,
examples, and future validation tools:

```bash
uv run python -m edcraft_validator examples/valid_square.json
```

It is not part of normal template-based question expansion.

## Architecture

```text
application/generate_template.py   frontend-facing use case
domains/code/templates.py          code template schema, prompt, approval, expansion
generation/base.py                 provider-neutral template protocol
generation/registry.py             explicit provider selection and extension point
generation/openai.py               OpenAI and SocLaas adapters
generation/ollama.py               Ollama adapter
executor.py + _worker.py            batched Docker execution
domains/code/pipeline.py           standalone concrete-question validation pipeline
```

To add another model, implement `QuestionTemplateGenerator.generate_template`,
register its factory with `register_template_provider`, and add an adapter test.
The application and CLI do not need provider-specific branches.

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

The real OpenAI template-authoring test is opt-in locally and runs for same-repo
pull requests when the GitHub secret is available:

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run pytest -m openai_live -q
```

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for pinned dependencies and
environment details.
