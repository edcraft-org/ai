# EdCraft AI Question Templates

EdCraft uses AI during authoring to create a reusable Python question template. It
then validates the template's complete finite input domain and generates concrete
questions deterministically without further AI calls.

Direct AI-to-question generation is intentionally not supported. This keeps API
cost proportional to the number of templates rather than the number of questions.

## Evolving workflow

Authoring accepts a domain, free-form prompt, and difficulty. In one structured
response the model returns a reusable proposal plus recommended checks. The
application resolves the domain's allowed tools from MCP once per authoring job and
supplies their full definitions to the model. The model then requests the selected
checks through an application-mediated MCP loop. Failed proposals can be revised
for at most three complete attempts, with fixed check membership.

- [Workflow specification and implementation order](docs/question-generation/README.md)
- [PlantUML sequence diagram](docs/question-generation/generate-template.puml)
- [Goals and milestones](GOALS.md)
- [GitHub Projects setup](docs/project-tracking.md)

## Current workflow

```text
domain + free-form prompt + difficulty + provider
  -> freeze domain-allowed MCP catalogue
  -> model returns proposal + fixed check plan
  -> model requests checks; application inserts the current candidate
  -> MCP returns evidence for every selected check
  -> failures return to the model for revision (at most three complete attempts)
  -> all checks pass: package canonical answers and selected distractors
  -> otherwise: needs_review/error with latest proposal and full evidence history
  -> deterministic questions generated locally from a reusable artifact
```

The initial proposal and plan use one structured model response. Checking, correction,
and final evidence acknowledgement use subsequent model calls. The application
supplies the current candidate and request-owned distractor count, so model tool
arguments cannot substitute a different template. Only model-selected tools run.
The code domain requires execution-derived canonical answers and selected distractors
before it can finalize a reusable template. A structure-only plan cannot supply them.
Authoring does not repair answers or add fallback distractors behind the model's back.

Results include `status`, `proposal`, `fixed_plan`, the frozen catalogue, all attempt
snapshots and tool evidence, and an optional `artifact`. `checked` includes a reusable
artifact; `needs_review` includes three failed attempts or missing finalization data;
`error` records an interrupted/incomplete conversation. Model acknowledgement failure
is recorded separately as `feedback_error`; it cannot erase completed evidence.
Generating a question from a validated template uses no AI, execution tool, or
per-question validation call.

`Validated` means that deterministic checks passed; it does not mean that a user
approved the content. The future frontend will present the validated template for a
human approve/reject decision before allowing question generation.

Successful authoring and existing-candidate checking assign an `artifact_id`
(`sha256:...`) after finalization. This hashes the complete serialized artifact and
its provenance, excluding only the ID itself. The record includes the final proposal,
original fixed plan, frozen catalogue, every attempt and its evidence, original
request, initial model messages, response schema, and non-secret provider settings.
Timings and call IDs are part of the record, so a new check run can produce a new ID
even for unchanged content. This ID identifies the saved record; it is not an approval
or a signature, and generation does not perform tamper verification.

Code artifacts record `generator_version: "code-question-v1"`. To preview an artifact,
use the same `generate` command with representative seeds and keep the returned
`artifact_id` and `seed`. Loading that saved artifact and using the same seed reproduces
the question locally. Its existing template ID still controls parameter selection,
so adding provenance does not change seed behavior. Domain finalization packages
checked answers and selected recipes without changing code or question wording.
The final model acknowledgement belongs to checking, before this local finalization.

Approval and revision enforcement are deferred to Issue 40. Internal artifacts are
trusted application data. Old authoring records missing required provenance fields
must be regenerated; there is no schema migration during development.

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

The `author` command writes the full authoring result. Exit code 0 means `checked`,
2 means `needs_review` or a recorded workflow error, and 1 means an initial
configuration/request/generation failure. Extract its `artifact` before passing it
to `generate`; failed results have no reusable artifact:

```bash
jq -e '.artifact // error("No reusable artifact")' /tmp/validated-template.json \
  > /tmp/reusable-template.json
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

## Check an existing candidate through MCP

`validate` requires a provider: the model selects relevant checks and requests their
execution through MCP. It does not regenerate or revise the supplied candidate.
Every selected check runs once, even when another selected check fails. There is no
user-selected check list or fixed validation pipeline.

```bash
uv run python -m edcraft_validator.cli validate \
  --domain code --provider openai --model gpt-5-mini \
  examples/templates/arithmetic_linear.json \
  --output /tmp/arithmetic-check-result.json
jq -e '.artifact // error("No reusable artifact")' /tmp/arithmetic-check-result.json \
  > /tmp/validated-arithmetic-template.json
```

The output envelope and exit codes match `author`: `checked`/0, `needs_review` or a
recorded error/2, and initial input/configuration/planning failure/1. The report
retains the exact candidate, model-selected plan, catalogue and execution evidence.
A reusable artifact is produced only when all selected checks pass and domain
finalization succeeds. Missing execution-derived answers yields `needs_review`;
the application does not insert the omitted check. Human approval is separate
Issue 40 work; `checked` does not mean approved.

For code candidates, the application requires two distractors when two are supplied,
and three when three or more are supplied. The semantic MCP operation executes every
finite input combination in a single local Python batch and selects only supplied
recipes. Wrong answers or insufficient valid distractors fail without automatic
repair or fallback recipes. Use `author` for the model's bounded correction loop.

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
- Answers: Python execution supplies canonical answers. A differing proposed answer
  fails the check; only the model's explicit authoring revision can correct it.
- Expression safety: at most 500 source characters and 100 syntax nodes; numeric
  intermediates are bounded to magnitude 1 billion, individual sequences to 100
  items, and complete nested values to a cumulative logical size of 1,000.
- Distractors: the provider proposes misconception candidates in the same call. The
  finite-domain validator searches candidate subsets to retain the requested two
  or three globally unique expressions with reason templates. Too few valid
  distractors fail the check; no fallback recipes are added.
- Reproducibility: deterministic seed selection and a stable saved-artifact identity.
  Artifacts retain the resolved provider/model, non-secret request settings, domain,
  prompt/difficulty, prompt version and messages, response schema, fixed plan,
  catalogue, and complete attempt evidence. Ollama snapshots temperature and token
  limits when constructed; OpenAI-compatible adapters record that sampling uses
  provider defaults rather than claiming an unspecified temperature or seed.
  API keys and other secrets are never stored.

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
not a security sandbox by itself. The validation job runs in a deployment-managed
container; this package does not create an additional container. The deployment
configures the job's filesystem, network, process, total-memory, and lifetime limits.
The worker subprocess adds a scrubbed environment, a host timeout, CPU
limits, a Linux 512 MiB address-space limit, static syntax restrictions, and the
trace-event limit as defense in depth.

## MCP validation tools

FastMCP is the authoritative registry for validation-tool names, descriptions,
input/output schemas, and versions. Code-domain operations implement the checks;
MCP wraps them with response deadlines and structured evidence. Run the stdio server with:

```bash
uv run python -m edcraft_validator.mcp
```

The initial catalogue contains:

- `code_verify_template_structure`: bounded static, expression, finite-domain, and
  rendering checks. It does not execute code or establish answer correctness.
- `code_validate_answers_and_distractors`: exhaustively executes the declared finite
  domain once, rejects any proposed-answer mismatch, and then selects only a valid
  subset of model-proposed distractors. It neither corrects answers nor inserts
  fallback distractors.
- `code_require_features`: checks for explicitly requested syntax features reachable
  from the entry function. Presence does not establish pedagogical relevance or
  difficulty.

Every available tool returns the shared `ToolEvidence` contract with `passed`,
`failed`, or `error` status. `failed` means the tool completed and disproved a
candidate property; `error` means execution could not establish a result. Invalid
arguments and unavailable names remain MCP protocol errors because no tool call ran.
MCP response deadlines are five seconds for static tools and
`64 * per_case_timeout + 2` seconds for the execution tool. An expired deadline
returns `error` evidence with `CHECK_TIMEOUT`; late results are discarded. This
cancels waiting, not the synchronous worker thread. The Python subprocess retains
its own termination limits, and the deployment-managed job supplies the outer
resource and lifetime limits.
The application uses a job-scoped in-process MCP client for discovery and execution.
Calls validate against frozen schemas and tool versions; model calls cannot override
application-owned inputs. Both `author` and `validate` use this MCP path; no legacy
pipeline remains.

## Architecture

```text
edcraft_validator/
├── application/
│   ├── authoring_contracts.py     attempts, execution records and reviewable results
│   └── template_workflow.py       bounded MCP authoring loop and local expansion
├── artifact_contracts.py          shared artifact and provenance contracts
├── value_comparison.py            typed answer and distractor comparison
├── llm/
│   ├── llm_contracts.py           provider protocol, request, and selection contracts
│   ├── llm_errors.py              provider-independent generation failures
│   ├── provider_registry.py       model-provider lookup
│   ├── openai_compatible_provider.py  OpenAI and SocLaas adapter
│   └── ollama_provider.py         Ollama adapter
├── mcp/
│   ├── evidence.py                shared pass/fail/error tool result contract
│   ├── client.py                  job-scoped MCP list/call adapter
│   ├── code_tools.py              tool registrations, deadlines, and evidence
│   └── server.py                  injectable FastMCP server factory
├── domains/
│   ├── domain_contract.py         contract implemented by every domain
│   ├── domain_registry.py         domain lookup used by entry points
│   └── code/
│       ├── code_domain.py         code prompting, validation, and expansion wiring
│       ├── code_types.py          code-domain aliases, topics, and answer targets
│       ├── code_schemas.py        request, proposal, template, and question schemas
│       ├── profiles.py            historical evaluation-profile fixtures
│       ├── validation_operations.py domain check sequences and result details
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
│           ├── structure_checks.py safe structure and rendering checks
│           ├── answer_checks.py   expression checks and canonical answers
│           ├── distractor_checks.py distractor selection and consistency
│           └── execution_check.py execution operation with an injected tool
├── validation/
│   └── validation_contracts.py    shared validation contracts
└── tools/
    ├── python_analysis.py         supported-Python static analysis
    ├── python_execution.py        local Python tool adapter
    └── python_worker.py           batched tracing implementation
```

Entry points resolve a domain and provider, then pass those objects to the
application. The domain supplies a generation specification containing messages and
a response schema. The provider handles its API and validates response text through
the supplied schema; it does not import domain models. The common response contract
is recorded as `code-template-v13+response-v3` in provenance.

```python
domain = create_domain("code")
request = domain.request_model.model_validate_json(request_json)
provider = create_model_provider(
    TemplateProviderSelection(provider="openai", model="gpt-5-mini")
)
result = TemplateApplication().author_template(
    request, domain=domain, provider=provider
)
```

The [sequence diagram](docs/question-generation/generate-template.puml) describes
the implemented checking loop. User approval remains a separate planned integration.

### Adding a domain, provider, or check

To add a domain:

1. Define its request, proposal, candidate, validated artifact, and question schemas.
   The validated artifact extends `ValidatedTemplateArtifact` for provenance.
2. Implement `DomainModule`: build generation and existing-candidate check-planning
   specifications, build candidates, declare allowed MCP names and application-owned
   tool bindings, finalize from successful evidence, and generate questions. Keep
   these methods independent of provider names. Existing-candidate bindings receive
   `request=None` and derive required values from the candidate.
3. Register its factory in `domains/domain_registry.py`. Supply its request data through
   `--request-json`; the application and generic CLI handler need no changes.
4. Test a successful workflow and rejection before finalization. The example domain
   in `tests/test_template_workflow.py` demonstrates its own MCP tool and finalizer;
   `tests/test_cli.py` demonstrates registration and request parsing.

To use another model from an existing provider, pass `--model`. To add a provider,
implement `ModelProvider.generate`, `tool_turn`, and `generation_settings`: parse
structured proposals, normalize native tool calls, deliver correlated results,
and report only non-secret effective settings. Keep resolved settings consistent
across generation and checking turns.
Register its factory in `llm/provider_registry.py`; test transport errors and schema
validation with an injected client or mocked endpoint, then run a live compatibility
check. No domain imports belong in the adapter.

To add an authoring check, register an independent MCP tool with input/output
schemas, a version, bounded execution, and `ToolEvidence`. Add its name to the domain
allowlist. Tools own any internal prerequisites; the application does not construct
a second correctness plan. Test successful results, invalid inputs and failures.

### Shared MCP checking

`TemplateApplication.author_template` generates a proposal and check plan, then
permits up to three complete checking/correction attempts. `validate_template`
requires a provider and asks only for a check plan for its existing candidate, then
runs one complete checking attempt. Both return the same result envelope and share
catalogue freezing, native tool turns, argument binding, schema validation, evidence
recording and domain finalization. Neither path automatically adds checks.

Domain operations invoke low-level algorithms in their prerequisite order using a
fresh context. They return result details or raise a structured domain failure.
MCP translates those into `passed`, `failed`, or `error` evidence. The application
continues through the model-selected plan after individual failures. There is no
`ValidationPipeline`, required-check policy, fail-fast runner, or `CodeCheck` wrapper.

Unit tests exercise the domain operations directly; integration tests use actual
MCP clients/servers with scripted model responses, alongside opt-in live evaluation.
Execution dependencies are injected into the MCP server, not into `CodeDomain`.


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

The evaluation command runs the complete model-authoring and MCP validation workflow,
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

After the v10 prompt added a concrete example requiring the exact entry-function
identifier in `question_template`, one deterministic temperature-zero attempt
validated in 36.6 seconds. Six additional attempts at temperature 0.2 all validated,
averaging 39.9 seconds with a range of 29.8 to 49.9 seconds. The validator and
proposal schema were unchanged between the failing v9 baseline and these v10 runs.
