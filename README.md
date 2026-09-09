# EdCraft AI Question Templates

EdCraft uses an AI model once to author a reusable Python question template. It
then validates the template's complete finite input domain and generates concrete
questions deterministically without further AI calls.

Direct AI-to-question generation is intentionally not supported. This keeps API
cost proportional to the number of templates rather than the number of questions.

## Current workflow

```text
domain + topic + difficulty + provider
  -> AI proposes code, parameters, answer logic, and distractor candidates
  -> code domain builds identity, target, wording, and question type
  -> Python subset analysis
  -> all parameter combinations run through one local Python tool call
  -> globally valid distractor recipes selected from the candidates
  -> answers and selected distractors checked for every combination
  -> validated template + structured validation evidence
  -> deterministic questions generated locally from seeds
```

Template authoring makes one provider request for the requested misconception
candidates. The code domain adds mechanical fallbacks without another AI call.
Generating a question from a validated template uses no AI, execution tool, or
per-question validation call.

`Validated` means that deterministic checks passed; it does not mean that a user
approved the content. The future frontend will present the validated template for a
human approve/reject decision before allowing question generation.

## Setup

```bash
uv sync
```

Configure only the provider you intend to select:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5-mini
OPENAI_TIMEOUT_SECONDS=120
OPENAI_MAX_RETRIES=1

OLLAMA_MODEL=qwen2.5-coder:14b
OLLAMA_TIMEOUT_SECONDS=300
OLLAMA_TEMPERATURE=0
OLLAMA_NUM_PREDICT=2048
```

Provider selection is always explicit through `--provider`.
Model selection can also be explicit through `--model`; when it is omitted, the
selected provider's environment setting is used.

## Author and validate a template

OpenAI uses strict Structured Outputs:

```bash
uv run python -m edcraft_validator.cli author \
  --provider openai \
  --domain code \
  --model gpt-5-mini \
  --topic arithmetic \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/validated-template.json
```

Ollama uses its native structured endpoint with a simple provider-specific wire
schema. The adapter strictly normalizes that response into the same local proposal
contract used by OpenAI:

```bash
/usr/bin/time -p uv run python -m edcraft_validator.cli author \
  --provider ollama \
  --domain code \
  --model qwen2.5-coder:14b \
  --topic loops \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/validated-loop-template.json
```

SocLaas is also registered through its OpenAI-compatible endpoint. Configure
`SOCLAAS_API_KEY`, `SOCLAAS_BASE_URL`, and `SOCLAAS_MODEL`, then select
`--provider soclaas`.

## Validate an existing raw template

The repository includes examples for integers, booleans, strings, and integer
lists:

```bash
uv run python -m edcraft_validator.cli validate \
  --domain code \
  examples/templates/arithmetic_linear.json \
  --output /tmp/validated-arithmetic-template.json

uv run python -m edcraft_validator.cli validate \
  --domain code \
  examples/templates/loop_iterations.json \
  --output /tmp/validated-loop-template.json

uv run python -m edcraft_validator.cli validate \
  --domain code \
  examples/templates/conditional_boolean.json \
  --output /tmp/validated-boolean-template.json

uv run python -m edcraft_validator.cli validate \
  --domain code \
  examples/templates/conditional_string.json \
  --output /tmp/validated-string-template.json

uv run python -m edcraft_validator.cli validate \
  --domain code \
  examples/templates/list_sum.json \
  --output /tmp/validated-list-template.json
```

Validation checks every value in the template's Cartesian product. All cases are
sent to one local Python tracing subprocess to avoid repeated startup costs.
Rejected templates raise structured diagnostics with a stable code, relevant
field, failing parameter values, and evidence from every completed check when
available; messages remain human-readable. Validated templates record the validator
version, assurance level, duration, and details for each structure, expression,
execution, answer, distractor, and rendering check. Tool-derived answers for every
finite input combination are stored in the validated artifact.

## Generate concrete questions locally

The same seed and validated template always produce the same output:

```bash
uv run python -m edcraft_validator.cli generate \
  --domain code \
  /tmp/validated-arithmetic-template.json --seed 42

uv run python -m edcraft_validator.cli generate \
  --domain code \
  /tmp/validated-arithmetic-template.json --seed 43
```

Each output records the template ID, seed, selected parameters, code, question,
answer target, answer, and distractors.
Rendered misconception reasons are preserved alongside their selected distractors.

## Currently supported

- Domain: Python code execution-trace MCQs.
- Providers: OpenAI, Ollama, and SocLaas.
- Topic selections: `arithmetic`, `conditionals`, `loops`, `functions`, and
  `lists`.
- Difficulties: `beginner`, `intermediate`, and `advanced`, each with a distinct
  validator-backed authoring profile per topic. Profiles enforce parameter and answer
  contracts plus broad, reachable code features without prescribing one exact formula
  or AST layout.
- Template parameters: one to three explicitly typed finite parameters. Supported
  kinds are integers, booleans, bounded printable strings, and bounded integer
  lists. Each parameter has two to four unique values.
- Exhaustive validation: at most 64 total parameter combinations.
- Answers: the Python execution tool's result is canonical. If the provider's proposed
  answer differs, the validator stores the corrected answers and considers the old
  answer as a distractor candidate.
- Expression safety: at most 500 source characters and 100 syntax nodes; numeric
  intermediates are bounded to magnitude 1 billion, individual sequences to 100
  items, and complete nested values to a cumulative logical size of 1,000.
- Distractors: the provider proposes the requested misconception candidates in the
  same call. Code template construction appends type-compatible deterministic
  fallbacks, and
  the finite-domain validator searches candidate subsets to retain the requested two
  or three globally unique expressions with reason templates. Corrected templates
  are still rejected when too few valid distractors remain.
- Reproducibility: deterministic seed selection. AI-authored, validated artifacts
  also record the resolved provider and model, domain, authoring request, base prompt
  version, generation timestamp, and generation time. API keys and other secrets are
  never stored.

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
template is checked against all finite parameter combinations with the real tracer.

Supported generated Python includes basic expressions, assignments, `if`, bounded
`for` loops, helper functions, and a small allowlist of safe built-ins. The safety
gate rejects imports, attributes, classes, decorators, recursion, comprehensions,
`while`, file access, networking, and dynamic execution.

## Validation boundary

The code domain uses a local Python tracing subprocess with per-case timeouts and a
100,000 user-code trace-event limit. EdCraft's pinned `step-tracer` supplies return
values and execution counts. The current tool supports deterministic validation; it
is not a security sandbox for untrusted Python.

## Architecture

```text
application/templates.py           domain-agnostic authoring and expansion workflow
domains/base.py                    contract implemented by every domain
domains/registry.py                domain lookup used by the application
domains/code/module.py             code prompt, validation, and expansion wiring
domains/code/authoring.py          code generation request and Ollama wire schema
domains/code/models.py             code authoring request
domains/code/evaluation.py         real-provider code-template evaluation
domains/code/templates/models.py   code template data contracts
domains/code/templates/authoring.py prompt construction and template building
domains/code/templates/expressions.py restricted deterministic expressions
domains/code/templates/validation.py exhaustive template validation
domains/code/templates/generation.py deterministic question expansion
domains/code/capabilities.py       supported profiles and their machine-readable rules
generation/base.py                 domain-agnostic structured generation request
generation/registry.py             model-provider lookup
generation/openai.py               OpenAI and SocLaas adapters
generation/ollama.py               Ollama adapter
validation/pipeline.py             domain-agnostic validation evidence orchestration
validation/contracts.py            shared validation contracts
tools/python_analysis.py           supported-Python static analysis
tools/python_execution.py          local Python tool adapter
tools/python_worker.py             batched tracing implementation
```

To use another model from an existing provider, pass `--model`; no domain code
changes are required. To add another provider, implement `ModelProvider.generate`,
add its factory to the provider registry, and add an adapter test.

To add a domain, implement `DomainModule`, provide its request, proposal, candidate,
validated-template, and question models, build its `StructuredGenerationRequest`,
register its validation checks and question generator, then add it to
`domains/registry.py`. Providers and the application do not change. Domain-specific
tools all live under `tools/`; for example, future SymPy and Lean adapters can be
added without entering the code-template pipeline.

## Tests

Mocked provider tests run by default and make no paid API calls:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run only the complete code-template matrix locally:

```bash
uv run pytest tests/test_templates.py -q
```

The real OpenAI template-authoring test is opt-in locally and performs full template
validation. For same-repository pull requests, CI runs the equivalent evaluation
command, fails clearly if the `OPENAI_API_KEY` secret is missing, and uploads the
JSONL attempt record:

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run pytest -m openai_live -q
```

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for pinned dependencies and
environment details.

## Evaluate a real provider

The evaluation command runs the complete authoring and local validation workflow,
writes and flushes one JSONL record after each attempt (so completed work survives
an interruption), reports progress on stderr, and prints pass rate, failure codes,
and latency grouped by provider, resolved model, topic, and difficulty:

```bash
uv run python -m edcraft_validator.cli evaluate \
  --domain code \
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

The recorded pre-relaxation baseline for `qwen2.5-coder:14b` was 10 validated
templates out of 15 profiles (66.7%), averaging 44.1 seconds per attempt with the
bounded v8 prompt. Rerun the matrix before treating this as the baseline for the
broader profile contracts. Rejected model proposals are expected evaluation
outcomes; inspect their structured failure codes rather than treating rejection as
a validator failure.
