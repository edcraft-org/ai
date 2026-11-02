# Development

The application sequences authoring and checking. Domains own proposal schemas,
prompts, candidate construction and deterministic expansion. Provider adapters own
model communication. MCP adapters expose checking services and translate tool
metadata. CLI/server/worker boundaries construct dependencies and settings.

## Code ownership

| Responsibility | Location |
| --- | --- |
| Shared evidence data, without transport imports | `validation/check_contracts.py` |
| Domain behavior interface | `domains/domain_contract.py` |
| Application-facing tool interface | `application/ports.py` |
| Authoring orchestration and attempt records | `application/template_workflow.py`, `authoring_contracts.py` |
| Code authoring evaluation and report aggregation | `application/code_evaluation.py` |
| Typed public summaries and worker adapter | `application/authoring_api.py` |
| Code proposal, binding and finalization | `domains/code/code_domain.py`, schemas and candidate builder |
| Blinded difficulty prompts and rubric components | `domains/code/template_difficulty.py`, `difficulty_request.py` |
| Difficulty routing, verdict policy and evidence | `application/template_difficulty.py` |
| Shared relevance, code-template projection and revision gate | `application/relevance.py`, `application/code_relevance.py`, `domains/code/relevance.py` |
| Model adapters and measured judge execution | `llm/` |
| Check catalogue decoding and dispatch transport | `mcp/catalogue.py`, `mcp/client.py` |
| Default dependency construction | `bootstrap.py`, `mcp/server.py`, `cli.py` |

Package initializers must not construct servers. Shared evidence can be imported
without FastMCP or application services. `mcp/evidence.py` retains compatibility
exports. Application construction and deterministic expansion do not connect tools;
authoring obtains a connection when needed. Inject a tool client for tests.

The authoring coordinator prepares a frozen plan, executes attempts, and either
revises or finalizes. Check definitions are decoded once before dispatch; the
attempt loop does not interpret FastMCP tags. Keep schema validation, application
argument ownership, exact artifact binding and correctness prerequisites intact.
Prefer named stages and guard clauses within a module to extra layers/classes.

## Judge settings and policy

`JudgeSettings` is an immutable validated snapshot. The server loads it once and
passes it to difficulty and relevance. Library callers can supply it explicitly.
Environment variables are read by boundary constructors, not by routing policy.
The shared provider/model are independent of the selected authoring provider.

| Final assessment | Workflow |
| --- | --- |
| Forced decision confidence >=0.70, level matches | Pass; no reasoning call. |
| Forced decision accepted, level differs | Fail and request author revision. |
| Decision below 0.70 or invalid | One reasoning call using the same model. |
| Reasoning level matches | Pass. |
| Reasoning mismatch at self-confidence >=0.80 | Fail and request revision. |
| Reasoning mismatch below 0.80 | Pass policy with an advisory warning. |
| Reasoning cannot assess | Fail. |
| Reasoning error or exhausted deadline | Error; never a pass. |
| Relevance decision is relevant | Pass. |
| Relevance decision is irrelevant | Fail and request revision under the unchanged author prompt. |
| Relevance model, deadline or configuration failure | Error; stop without author revision. |

Token confidence and self-reported confidence are different, uncalibrated measures.
`details.difficulty_outcome` is the typed final policy result. The explicit key
avoids interpreting other domains' `outcome` fields as difficulty. Flat fields remain
for compatibility. `screen` and `judge` retain detailed stage reports; aggregate
usage includes both calls. Both paths bind the same exact template/rubric identity.

The decision gets at most 35 seconds within the existing 310-second judge budget;
reasoning receives only the remaining time. MCP allows 330 seconds per tool call.
A deadline stops waiting, not a synchronous inference thread. A fallback uses a
fresh transport; cleanup happens in the executing worker even after a timeout.
SDK retries are separate from application calls; use zero SDK retries for controlled
runs. Provider-owned HTTP clients close after completion; injected clients remain
owned by their caller.

`ModelProvider` supplies structured generation. `DecisionModelProvider` declares
the optional `decide(messages, labels)` capability. Decision adapters return label
probabilities; never substitute self-reported confidence for missing logprobs.
Relevance providers supply `score(request_text, question_text)` and may expose
`last_usage`, `generation_settings`, `served_model` and `close`. Accounting applies
to every injected provider; missing token metadata remains unknown.

`code_assess_template_relevance` adapts the shared text classifier to `ToolEvidence`;
it does not introduce a separate workflow. Template identity belongs to `candidate_builder.py`, independently of either judge.
The domain binds the original author prompt and the exact reusable candidate, including the checked distractor subset.
The classifier receives the actual code, question pattern, answer target and finite
parameters in readable text, excluding topic labels, requested difficulty,
answer and distractor recipes, and misconception explanations. Difficulty and relevance do not consume each other's
results. Their saved evidence binds the exact reusable template hash; relevance
also retains the request/text input hash, score, threshold and model usage.
Only selected checks run; the authoring prompt requests both assessments. The
standalone shared relevance report remains advisory for research callers.

There is no standalone validation workflow. Re-author changes through the existing
checking/revision loop; deterministic generation expands only checked artifacts.
Individual MCP checks and the evaluation command remain available for research.

The local Qwen reranker remains an explicit historical adapter. To reproduce local
runs, install `uv sync --locked --extra relevance` and download
`Qwen/Qwen3-Reranker-0.6B`; set `EDCRAFT_RELEVANCE_MODEL_PATH` if needed. It is not
the default server provider. The standalone concrete-MCQ judge remains available
for research evaluation; template authoring owns generation and revision.

## HTTP and worker boundary

`AuthoringJobCommand` contains a job ID, domain, author selection and JSON request
payload. The worker validates that payload against the domain's request schema.
`run_authoring_job_sync` is suitable for a job worker; async HTTP handlers use
`await run_authoring_job(...)` to keep the synchronous MCP runner off their event
loop. Do not call `TemplateApplication.author_template` directly in an async route.

The internal `AuthoringJobRecord.report` retains full attempt evidence for storage.
HTTP adapters return its `response`, which contains an `AuthoringSummary` with
stable outcomes, check codes and safe error messages. Raw exception strings in the
internal diagnostic report must not be rendered as public error text.

Job lifecycle (`queued/running/completed/failed`), checking outcome
(`checked/needs_review/error`) and human approval are independent. A completed job
may need review; checking never implies approval. The current summary is explicitly
`unreviewed`. Approval persistence and artifact-bound authorization remain M4 work.

`on_progress` receives immutable events from actual generation/checking/correction/
finalization stages. It runs on the worker thread; adapters must dispatch events
safely to their own queue/event loop. Observer failures are logged without changing
the authoring verdict. The existing HTTP backend still needs a handler, persistence
adapter and generated frontend client for these contracts; no endpoint is wired yet.

## Extending and verifying

Add domain behavior through `DomainModule` and register its factory. Add model
communication through the provider registry. Avoid new branches for domain names
inside shared orchestration. Keep deterministic reuse independent of model/tool
services. Python features are explicitly bounded; preserve worker isolation,
resource budgets, schema checks and rejection of unsupported code.

Register each domain's checking tools explicitly in `mcp/server.py` with
`domain:<name>` tags. A registry coverage test checks that every selectable domain
has discoverable tools. Evaluation orchestration belongs to the application layer.

OpenAI-compatible endpoints reuse the `openai` adapter with `OPENAI_BASE_URL` and
`OPENAI_MODEL`. `OPENAI_RESPONSE_FORMAT`, `OPENAI_GENERATION_MAX_TOKENS`
and `OPENAI_REASONING_EFFORT` configure existing transport
options without adding another provider. These settings do not guarantee support
for decision logprobs or reasoning controls on that endpoint.

Use shared fixture modules rather than importing fixtures from test modules.
Regression tests cover fresh-process imports, interchangeable provider accounting,
settings snapshots, deadlines, correction, evidence identity, worker threading and
public error projection. Focused mypy checks cover application/worker contracts and
settings. Run lint, formatting, type checks and appropriate tests before completion.

The production rubric is [v0.2](difficulty-rubric.md); the offline
[v0.3](difficulty-rubric-v0.3.md) reference remains separate. The rubric Markdown is
runtime data bundled by `pyproject.toml`; retain it and its schema/header checks.
See [evaluation](evaluation.md) before interpreting a policy change as an accuracy
improvement.
