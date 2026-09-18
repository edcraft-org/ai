# Template generation workflow

Status: agreed target design before implementation, 18 September 2026.
This document and [the sequence diagram](generate-template.puml) supersede the
earlier domain-selected validation plan and optional custom-prompt design.
The code and CLI on this docs branch still implement the older workflow.
Product goals and milestone scope are in [GOALS.md](../../GOALS.md).

## Decisions

1. The user selects a domain and submits a free-form prompt. Topic and difficulty
   may be expressed in that prompt; neither requires a predefined catalogue.
2. The application obtains a cached capability catalogue through an MCP client
   and supplies its documentation to the model with the domain specification.
   Discovery happens at connection/startup and explicit refresh, not every request.
3. The model returns a structured proposal and selected check names and arguments.
   It plans validation but does not execute checks or produce evidence.
4. The central validator validates and executes that plan through the MCP client.
   Check implementations may remain deterministic despite model-driven selection.
5. Domain-owned acceptance requirements specify required properties and scope,
   rather than a fixed list of tools.
6. Initially, use one generation/planning request and one validation pass. Return
   rejection to the user; automatic repair is deferred.
7. Review and approve technically validated templates before learner use. Allow
   deterministic previews for review. Approval UI and persistence follow in the
   frontend milestone; they do not exist merely because this diagram includes them.

## Input and model response

The public authoring request is:

```json
{
  "domain": "code",
  "prompt": "Create a Python MCQ about summing even numbers in a list. Use a loop and include accumulator mistakes as distractors."
}
```

Validate a nonblank prompt and resolve the domain at the application boundary.
Provider/model selection remains independent application configuration, with an
optional advanced override. Preserve the original prompt in provenance.
The domain supplies defaults such as option count in its generation instructions.
Unsupported or conflicting requirements must produce an actionable failure; do
not silently substitute an unrelated supported topic.

Combine domain instructions, the original user prompt, optional future retrieved
source context, the allowed check catalogue and a response schema. User prompts
and source passages cannot change tool permissions or acceptance rules.
No preliminary model call to map the prompt into the old topic/difficulty enum is
required. The proposal carries supported operational fields, including answer
target and answer kind, which the domain validates. Topic labels are descriptive
metadata, not execution dispatch keys. Profiles may remain optional presets and
historical evaluation fixtures.

The response contains `proposal` (the domain's proposal schema) and `checks`
(names and arguments validated against the catalogue). For example, these
illustrative selections accompany the proposal:

```json
{
  "checks": [
    {"name": "code_verify_execution_answers", "arguments": {}},
    {"name": "code_require_feature", "arguments": {"feature": "loop"}},
    {"name": "code_check_distractors", "arguments": {}}
  ]
}
```

These are planned capability names, not existing MCP endpoints. The validator
binds the actual candidate and prerequisite results to execution inputs. The model
need not duplicate the candidate in every check's arguments. The planner-facing
schema describes model-supplied arguments; the execution schema also includes
validator-supplied data. Their mapping belongs to the capability definition and is
tested, not inferred from arbitrary tool names.

Every provider returns this shared envelope. The domain supplies its proposal
schema; shared generation code defines the envelope containing proposal and checks.
The provider adapter extracts response content and invokes generic JSON/schema
parsing, for example `response_model.model_validate_json(content)`. Domains supply
no parser callback, and provider adapters do not import concrete domain classes.
The model generates data; local code still validates its structure before execution.

Provider-specific response envelopes and transport formats belong to adapters.
Domain field types and constraints belong to schemas. If a response representation
needs normalization, prefer an explicit shared representation and schema-level
validation; do not recreate a custom domain parser interface. Candidate construction
remains domain-owned and derives domain fields from already parsed data.

Use structured output for the proposal and plan. Native function calling and hosted
MCP execution are not required. Model quality and supported schema features still
require live tests for each exact model/version, including Ollama Qwen and LFM.

## Capability catalogue

Maintain one authoritative definition alongside each check implementation. Use it
to expose MCP tools and construct the catalogue given to the model. Document:

- Unique name, purpose, applicability and limitations.
- Model argument schema, execution input schema and structured output schema.
- Required inputs/prerequisites and checked values produced.
- Properties it can establish, evidence scope and assurance method.

MCP standardizes names, descriptions, schemas, discovery and invocation. EdCraft's
coverage, prerequisite and input-binding metadata are application-specific
extensions; MCP does not supply a validation policy or dependency scheduler.

Use only configured servers and allowed capabilities for the selected domain.
Resolve names to server/tool bindings in code, including server identity when names
collide. Supply documentation to the model, not credentials, callables or URLs for
it to choose. The server maintains a registry of check implementations and their
definitions. `tools/list` reads that registry; it does not execute or probe each tool.

Discover at connection/startup, following pagination, and cache the catalogue.
Reuse it across authoring requests. Refresh on reconnect, capability deployment or
supported list-change notifications. Pin the snapshot for an in-flight attempt;
changes apply to later attempts. Do not maintain a second hand-written catalogue.
Changed/unavailable execution contracts fail clearly rather than being silently
substituted; a cached definition does not guarantee the server is available.

Expose meaningful checks, not every helper. An execution-verification capability
can own parsing, static preconditions, bounded execution and answer extraction.
Keep unavoidable prerequisites explicit and let the validator resolve their order.
A small declared dependency list and stable ordering suffice initially; a general
workflow language is out of scope. Skills remain optional future guidance.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| Application | Resolve domain/provider, obtain cached catalogue, assemble generation input, coordinate validation/review and preserve provenance. |
| Domain | Own schemas, guidance, candidate construction, acceptance requirements, finalization and deterministic question expansion. |
| Model | Propose the template and select suitable checks and arguments. |
| Provider adapter | Send messages/schema, extract response content, invoke generic JSON/schema parsing and return the typed proposal and selections. |
| Validator | Validate selections, bind inputs, resolve prerequisites, execute checks, collect evidence and assess acceptance. |
| MCP client | Discover/cache tool definitions, refresh when needed, invoke bound server/tools and translate transport/protocol failures. |
| MCP server | Execute capabilities and return structured findings and checked values. |

The validator stays domain agnostic: it consumes contracts, dependencies and
acceptance requirements. Domain-specific comparisons or evidence interpretation
belong in domain capabilities. Adding a model does not change validation code.
Adding a domain supplies its schemas, guidance and capabilities.

## Validation and acceptance

Before execution, reject unknown checks, invalid arguments, unsupported inputs,
unresolvable dependencies or cycles. Technical constraints apply regardless of
selection: the model cannot bypass execution isolation, safety checks or limits.

Required properties for supported code MCQs include answer evidence across the
declared finite parameter domain, valid distinct options and renderable questions.
The model selects capabilities. The validator may add declared prerequisites but
must not silently replace the plan with the old fixed list. Record selected checks
and resolved prerequisites separately. Missing required coverage is incomplete
validation, not acceptance of an empty or weak plan.

Metadata establishes eligibility to run; actual results establish success. A
successful MCP call may contain a failed or incomplete check. Validate result
schemas, preserve errors and stop on blocking failures. Advisory quality findings
remain visible without being misrepresented as correctness proof.

Distinguish mandatory correctness properties from requested quality objectives.
Record unverified prompt requirements. If a requested property is essential for
acceptance and no capability can establish it, return incomplete. Arbitrary
natural-language coverage cannot be guaranteed by matching capability names;
evaluate interpretation and selection with human-labelled examples.

Results carry `passed`, `failed` or `incomplete`, findings, checked values and actual
scope. Retain `proof`, `exhaustive`, `bounded`, `sampled` and `heuristic` assurance.
Exhaustive means every declared finite case, not every possible program input.
Model confidence cannot override failures; heuristic reviews remain labelled.

Checks may derive canonical answers and select distractors as today. Record checked
values and their relationship to the candidate. Finalization packages these values
without new generation or execution. A material proposal change requires fresh
validation; evidence for an older candidate cannot approve a different artifact.

## Review, reuse and provenance

Present the template, report, limitations, any citations and deterministic previews.
Bind approval to the exact finalized artifact version. Rejected artifacts remain
unavailable to learners. Generate questions from approved artifacts and seeds
without model calls, MCP calls or per-question validation.

Record the original prompt, domain, provider/model and settings, prompt/schema
versions, catalogue snapshot and capability versions, selected and resolved plans,
candidate/final artifact hashes, actual results/scopes, timings and user decision.
Record source identifiers/hashes when retrieval is added. Never store credentials
or hidden model reasoning. Model generation is not guaranteed reproducible;
expansion from a recorded artifact and seed must be reproducible.

## Implementation order and completion criteria

1. Remove domain parser callbacks. Adapters extract content and use generic parsing
   against supplied schemas, retaining domain-independent provider implementations.
2. Define free-form input and the proposal/check-selection envelope. Remove required
   profile lookups from generation and candidate construction.
3. Define capability contracts and expose a small code-check MCP server, retaining
   deterministic algorithms and technical constraints.
4. Add cached discovery and pass the same allowed snapshot to every provider.
5. Extend the validator for selected checks, prerequisites, input binding, MCP
   execution, failures and acceptance coverage.
6. Adapt finalization, provenance and deterministic previews/reuse. Keep technical
   validation distinct from later user approval.
7. Update tests and run live evaluations. Track frontend approval and knowledge-base
   work separately in GitHub Projects.

The [implementation issue list](../project-tracking.md#implementation-issues) records
GitHub issues and their dependencies. Each implementation issue includes its own
focused tests; the final evaluation issue verifies the integrated workflow.

Test successful novel-topic prompts, malformed output, unknown checks, invalid
arguments, missing coverage, unmet prerequisites, unavailable servers, timeouts,
malformed results and outdated evidence. Verify that generation never executes
tools and the validator executes selections and prerequisites. Measure missed and
unnecessary checks, invalid arguments, false acceptance/rejection, cost and latency
separately from schema compliance. Use the same fixtures and rules across providers.

## References

- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [OpenAI tool descriptions](https://developers.openai.com/api/docs/guides/function-calling)
- [Ollama structured generation](https://docs.ollama.com/api/chat)
- [GitHub Projects setup](../project-tracking.md)
