# EdCraft AI Question Templates

EdCraft uses an AI model once to author a reusable Python question template. It
then validates the template's complete finite input domain and generates concrete
questions deterministically without further AI calls.

Direct AI-to-question generation is intentionally not supported. This keeps API
cost proportional to the number of templates rather than the number of questions.

## Evolving workflow

Authoring accepts a domain, free-form prompt, and difficulty. In one structured
response the model returns a reusable proposal plus recommended checks. The current
validator still runs its complete deterministic pipeline; later implementation
issues will expose those checks through MCP and execute the recommended fixed plan.

- [Workflow specification and implementation order](docs/question-generation/README.md)
- [PlantUML sequence diagram](docs/question-generation/generate-template.puml)
- [Goals and milestones](GOALS.md)
- [GitHub Projects setup](docs/project-tracking.md)

## Current workflow

```text
domain + free-form prompt + difficulty + provider
  -> AI proposes wording, code, entry function, answer target, parameters,
     answer logic, distractors, and recommended checks
  -> code domain builds identity and question type
  -> Python subset analysis
  -> all parameter combinations run through one local Python tool call
  -> globally valid distractor recipes selected from the candidates
  -> answers and selected distractors checked for every combination
  -> validated template + structured validation evidence
  -> deterministic questions generated locally from seeds
```

Template authoring makes one provider request for the complete proposal and its
recommended checks. The model must supply enough usable distractors; the code domain
does not add topic-profile-specific fallbacks.
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
  --prompt "Create an arithmetic MCQ about adding and subtracting integers." \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/validated-template.json
```

All providers use the same domain-owned response schema. Parameter values arrive as
native JSON numbers, booleans, strings, or integer arrays selected by each
parameter's `kind`; the provider validates the response through that schema. Ollama
sends the same schema through its native structured endpoint:

```bash
/usr/bin/time -p uv run python -m edcraft_validator.cli author \
  --provider ollama \
  --domain code \
  --model qwen2.5-coder:14b \
  --prompt "Create a loop-tracing MCQ about accumulating a sequence." \
  --difficulty beginner \
  --num-distractors 3 \
  --output /tmp/validated-loop-template.json
```

SocLaas is also registered through its OpenAI-compatible endpoint. Configure
`SOCLAAS_API_KEY`, `SOCLAAS_BASE_URL`, and `SOCLAAS_MODEL`, then select
`--provider soclaas`.

For any domain, supply a JSON file matching that domain's request model:

```bash
uv run python -m edcraft_validator.cli author \
  --domain code --provider openai \
  --request-json examples/code-request.json \
  --output /tmp/validated-template.json
```

For code, that file can contain:

```json
{"prompt": "Create an arithmetic MCQ.", "difficulty": "beginner", "num_distractors": 3}
```

`--request-json` cannot be combined with `--prompt`, `--difficulty`, or
`--num-distractors`. Omitting the
distractor count uses the code request model's default of three. Request data is
validated before a model provider is created. A new domain can declare different
request fields without changing this handler.

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
- Prompt: free-form within the supported safe Python and reusable-MCQ contracts.
- Difficulties: `beginner`, `intermediate`, and `advanced`. They are preserved in
  provenance but are not yet independently calibrated by a deterministic checker.
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
- Distractors: the provider proposes misconception candidates in the same call. The
  finite-domain validator searches candidate subsets to retain the requested two
  or three globally unique expressions with reason templates. Corrected templates
  are still rejected when too few valid distractors remain.
- Reproducibility: deterministic seed selection. AI-authored, validated artifacts
  also record the resolved provider and model, domain, authoring request, base prompt
  version, generation timestamp, and generation time. API keys and other secrets are
  never stored.

The model selects one of the tracer's supported answer targets:

| Target | Meaning |
| --- | --- |
| `return_value` | Entry-function return value |
| `branch_executions` | Number of evaluated `if` conditions |
| `loop_iterations` | Total loop-body iterations |
| `loop_executions` | Number of loop statements encountered |
| `function_calls` | Traced function calls, including the entry call and safe built-ins |

### Code-domain coverage matrix

The repository retains one exhaustively validated template for each historical topic
and difficulty pair (15 total). These are regression and evaluation fixtures, not an
authoring allowlist:

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

`CodeDomain` assembles `ExecutionCheck` with an injected `PythonExecutionTool`.
The default adapter in `tools/python_execution.py` sends every case for one candidate
to one `tools/python_worker.py` subprocess, which uses EdCraft's pinned `step-tracer`
to return values and execution counts. Per-case timeouts and a 100,000 user-code
trace-event limit bound tracing. This tool supports deterministic validation; it is
not a security sandbox for untrusted Python.

## Architecture

```text
edcraft_validator/
├── application/
│   └── template_workflow.py       domain-agnostic authoring and expansion workflow
├── artifact_contracts.py          shared artifact and provenance contracts
├── value_comparison.py            typed answer and distractor comparison
├── llm/
│   ├── llm_contracts.py           provider protocol, request, and selection contracts
│   ├── llm_errors.py              provider-independent generation failures
│   ├── provider_registry.py       model-provider lookup
│   ├── openai_compatible_provider.py  OpenAI and SocLaas adapter
│   └── ollama_provider.py         Ollama adapter
├── domains/
│   ├── domain_contract.py         contract implemented by every domain
│   ├── domain_registry.py         domain lookup used by entry points
│   └── code/
│       ├── code_domain.py         code prompting, validation, and expansion wiring
│       ├── code_types.py          code-domain aliases, topics, and answer targets
│       ├── code_schemas.py        request, proposal, template, and question schemas
│       ├── profiles.py            historical evaluation-profile fixtures
│       ├── code_features.py       AST feature extraction and feature predicates
│       ├── prompt_builder.py      code prompts and structured generation request
│       ├── proposal_response.py   typed provider response schema
│       ├── candidate_builder.py   canonical candidate construction
│       ├── safe_expressions.py    restricted deterministic expressions
│       ├── template_evaluator.py  repeatable real-provider evaluation
│       ├── question_generator.py  deterministic question expansion
│       ├── text_rendering.py      safe question and reason-template rendering
│       └── checks/
│           ├── validation_context.py typed intermediate validation values
│           ├── check_wrapper.py   check metadata and tool-failure outcomes
│           ├── structure_checks.py safe structure and rendering checks
│           ├── answer_checks.py   expression checks and canonical answers
│           ├── distractor_checks.py distractor selection and consistency
│           └── execution_check.py execution operation with an injected tool
├── validation/
│   ├── validation_contracts.py    shared validation contracts
│   └── check_runner.py            central runner for domain-supplied checks
└── tools/
    ├── python_analysis.py         supported-Python static analysis
    ├── python_execution.py        local Python tool adapter
    └── python_worker.py           batched tracing implementation
```

Entry points resolve a domain and provider, then pass those objects to the
application. The domain supplies a generation specification containing messages and
a response schema. The provider handles its API and validates response text through
the supplied schema; it does not import domain models. The common response contract
is recorded as `code-template-v8+response-v2` in provenance.

```python
domain = create_domain("code")
request = domain.request_model.model_validate_json(request_json)
provider = create_model_provider(
    TemplateProviderSelection(provider="openai", model="gpt-5-mini")
)
validated = TemplateApplication().create_validated_template(
    request, domain=domain, provider=provider
)
```

The [PlantUML sequence diagram](https://github.com/edcraft-org/ai/blob/docs/template-generation-flow/docs/question-generation/generate-template.puml)
is maintained on the separate `docs/template-generation-flow` branch.

### Adding a domain, provider, or check

To add a domain:

1. Define its request, proposal, candidate, validated artifact, and question schemas.
   The validated artifact extends `ValidatedTemplateArtifact` for provenance.
2. Implement `DomainModule`: build the generation specification and candidate,
   assemble the validation context/checks/policy, finalize accepted results, and
   generate questions. Keep the specification independent of provider names.
3. Register its factory in `domains/domain_registry.py`. Supply its request data through
   `--request-json`; the application and generic CLI handler need no changes.
4. Test a successful workflow and rejection before finalization. The example domain
   in `tests/test_template_workflow.py` demonstrates its own context, check, and tool;
   `tests/test_cli.py` demonstrates registration and request parsing.

To use another model from an existing provider, pass `--model`. To add a provider,
implement `ModelProvider.generate`, send the supplied messages/schema through its
API, extract its response text, and validate it through the supplied response model.
Register its factory in `llm/provider_registry.py`; test transport errors and schema
validation with an injected client or mocked endpoint, then run a live compatibility
check. No domain imports belong in the adapter.

To add a domain check, implement `run(context)` with a name and assurance level,
or use a function with the existing `CodeCheck` wrapper for code-domain operations.
Add it to the domain's ordered plan after its prerequisites and include its name
in the required-check policy when it must run. If it needs a tool, inject that tool
into the check operation when assembling the plan. Tool adapters live under
`tools/`; the runner never selects or calls them directly. Test tool failures as
well as successful results. A class is useful when storing dependencies, as in
`ExecutionCheck`; pure operations can remain functions.

### Central validation flow

The application asks the selected domain for a `ValidationPlan`: a typed context,
ordered checks, and a policy listing required checks. It passes those directly to
`ValidationPipeline.validate`, which has no code-domain imports or domain switches.

```python
plan = domain.prepare_validation(candidate, request=request)
report = pipeline.validate(context=plan.context, checks=plan.checks, policy=plan.policy)
report.raise_for_failure()
validated = domain.finalize_template(plan.context, report)
```

Each check implements `run(context)` and returns a `CheckResult`. The domain owns
its check logic and tool dependencies. The runner records names, assurance levels,
durations, and evidence, and applies the supplied acceptance policy. Unexpected
programming errors propagate rather than being reported as invalid templates.
Code check operations under `domains/code/checks/` take only the typed context and
return their findings.
The small `CodeCheck` wrapper attaches metadata and preserves tool-error diagnostics;
substantial algorithms such as distractor selection remain separate helpers.

The code context carries parsed expressions, execution results, canonical answers,
and selected distractors between checks. Its order is explicit: structure and
expression checks precede execution; canonical answers precede distractor checks.
Domain contract tests verify unique check names, required-check registration,
prerequisite ordering, and the context type. These internally supplied plan
invariants are not rechecked on every run. Caller-supplied models and tool outputs
still receive boundary validation.
There is no automatic dependency discovery or parallel check execution. Contexts
are created fresh for each validation and are not intended to be reused.

A check can return `None` when it does not apply. A required check must have a
passing result; a missing or inapplicable required check cannot produce acceptance.
For manual code templates, distractor selection is conditional on answer correction;
distractor consistency is always required. Authoring also requires selection of the
requested distractor count.

Any failed or incomplete check stops subsequent checks and rejects the candidate,
even if that check is not in the required set. Required checks must additionally
be present in the completed evidence. There is no configurable continuation or
advisory acceptance mode; add that only alongside a concrete quality-check workflow.

Tool timeouts, trace/resource limits, and tool infrastructure failures are recorded
as `incomplete`, preserving their diagnostic codes. Both failed and incomplete
required checks reject the candidate. The code domain still corrects proposed
answers using execution results and stores every canonical answer. Finalization
packages only checked content and refuses an unaccepted report.

`TemplateApplication` coordinates validation for normal application callers.
Callers pass domain and provider objects directly; CLI and evaluation entry points
resolve names and configuration through the registries. Validation and question
generation need only the domain object.
Tests use `TemplateApplication.validate_template` for end-to-end validation and
domain plans with `ValidationPipeline.validate` for focused check behavior.
`CodeDomain` directly assembles plans and finalizes artifacts; it does not run
validation itself. Check operations live in focused code-domain modules, and
`ExecutionCheck` receives its execution tool and timeout directly. Each domain calls
its own deterministic question-generation function; model providers and tools remain
injectable. The central runner exposes only the plan-based `validate` method.
Individual operations should be supplied as checks; evidence belongs to the returned
report rather than mutable runner state.

### Import-path migration

This layout refactor changes internal Python import paths. Update integrations that
import implementation modules directly to the paths shown above; for example, model
provider contracts now live in `edcraft_validator.llm.llm_contracts`, the code domain
in `edcraft_validator.domains.code.code_domain`, and validation contracts in
`edcraft_validator.validation.validation_contracts`. Class and function names are
unchanged. CLI commands, flags, and serialized template/question artifacts remain
compatible.

## Tests

Mocked provider tests run by default and make no paid API calls:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run only the complete code-template matrix locally:

```bash
uv run pytest tests/test_code_integration.py::test_template_is_exhaustively_validated -q
```

The real OpenAI template-authoring test is opt-in locally and performs full template
validation. For same-repository pull requests, CI runs the equivalent evaluation
command, fails clearly if the `OPENAI_API_KEY` secret is missing, and uploads the
JSONL attempt record:

```bash
RUN_OPENAI_LIVE_TESTS=1 uv run --env-file .env pytest -m openai_live -q
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

The issue #35 profile-free v9 prompt was also evaluated on 2026-09-25 with six
`arithmetic`/`beginner` attempts using Ollama 0.33.0 and
`qwen2.5-coder:14b`. None validated: all six failed `template_structure` with
`QUESTION_TEMPLATE_INVALID` because the model-authored `question_template` did not
name its selected entry function. Mean end-to-end latency was 45.8 seconds (35.3 to
59.8 seconds). This result is retained as a model-compatibility baseline; the static
requirement was not relaxed.
