# Template generation workflow

Status: agreed target design, 23 September 2026. This document and
[the sequence diagram](generate-template.puml) define the target workflow.
Implementation includes catalogue resolution, model-directed MCP execution and
three-attempt correction (#38). Artifact approval/persistence remains follow-up work. Product scope and milestone order are in
[GOALS.md](../../GOALS.md).

The [Issue 38 code trace and migration proposal](issue-38-architecture.md) maps the
pre-change implementation to this target. See the [implementation report](issue-38-results.md)
for the delivered behavior and verification.

## Decisions

1. Every request contains a domain, a free-form prompt, and a required `beginner`,
   `intermediate`, or `advanced` difficulty. Provider and model remain separate
   configuration.
2. The selected domain supplies generation instructions, a proposal schema, and the
   names of MCP tools allowed for that domain.
3. MCP is authoritative for each tool's description, input and result schemas, and
   version. Domain modules implement the operations exposed by those tools. The application resolves the domain's names against MCP and
   freezes those definitions for the generation job.
4. In its first response, the model returns both a complete proposal and a fixed
   recommended check plan selected from the offered tools.
5. The model requests the selected checks. The application enforces the frozen
   allowlist and plan, calls MCP, records the evidence, and returns it to the model.
6. All selected checks must pass in one complete attempt. After a failed attempt,
   the model may revise the proposal and arguments, then reruns the same check plan.
   The workflow permits at most three complete attempts.
7. A third failed attempt returns the latest proposal and evidence as
   `needs_review`. A passed proposal becomes a reviewable artifact; it is not
   learner-facing until a user approves that exact version.
8. Approved templates generate questions deterministically, without further model
   or MCP calls.

There is no central validator. The application owns orchestration and permission
checks, domain modules own validation algorithms exposed through MCP, and the model owns
check selection and correction. Provider-managed MCP execution is outside the
initial scope because the application must preserve permissions, limits, evidence,
and consistent behavior across local and hosted models.

## Request and response

The public authoring request is:

```json
{
  "domain": "code",
  "prompt": "Create a Python MCQ about summing even numbers in a list. Use a loop and include accumulator mistakes as distractors.",
  "difficulty": "intermediate"
}
```

The application validates the request, resolves the domain, and preserves the
original values in provenance. Topic profiles may remain presets and evaluation
fixtures, but they do not gate free-form authoring. Unsupported requests return an
actionable error rather than being silently changed to a supported topic.

The domain returns a generation specification such as:

```json
{
  "instructions": "Generate one reusable Python multiple-choice template.",
  "proposal_schema": "CodeTemplateProposalV1",
  "allowed_tool_names": [
    "code_verify_template_structure",
    "code_validate_answers_and_distractors",
    "code_require_features"
  ]
}
```

The application resolves those names to current MCP descriptions and schemas and
sends them with the prompt, difficulty, instructions, and proposal schema. The
model's first response contains the proposal and a nonempty fixed check plan:

```json
{
  "proposal": {
    "question_template": "What value does sum_even({values}) return?",
    "code": "...",
    "entry_function": "sum_even",
    "parameters": [
      {"name": "values", "kind": "integer_list", "values": [[2, 4], [6, 8]]}
    ],
    "answer_target": "return_value",
    "answer_expression": "sum(values)",
    "distractors": [
      {"expression": "len(values)", "reason_template": "Counts values instead of adding them."},
      {"expression": "sum(values) + 2", "reason_template": "Adds one extra even value."}
    ]
  },
  "checks": [
    {"name": "code_verify_template_structure", "arguments": {}},
    {"name": "code_validate_answers_and_distractors", "arguments": {}},
    {"name": "code_require_features", "arguments": {}}
  ]
}
```

This is one proposal-and-planning response. It does not mean that the model executes
tools inside that response. Subsequent model turns request calls and receive the
actual evidence. Provider adapters normalize native tool-call formats into the
shared application representation. Domains supply schemas and never supply parser
callbacks.

The recommendation now uses names resolved from the authoritative MCP catalogue,
and provenance records the complete frozen definitions. The application executes only the fixed plan through MCP. Initial planning
arguments are empty; later native calls supply check-specific values such as
`{"required": ["loop"]}`. The application removes candidate and request-owned inputs
from callable schemas, rejects attempted overrides, and inserts the canonical
candidate and original distractor count before dispatch.

## Tool catalogue

FastMCP maintains the deterministic tool registry. Each exposed tool documents:

- A stable unique name and a description that says when to select it.
- Its supported inputs, limitations, and structured result schema.
- What property it checks and the scope and assurance of its evidence.
- Its implementation, timeout, resource, and isolation constraints where relevant.

The application queries MCP once at the start of a generation job, resolves only
the selected domain's allowed names, and freezes the resulting catalogue snapshot
for all retries. A missing or duplicate allowed name fails before model generation.
The domain does not duplicate tool descriptions or schemas. MCP `tools/list` reads
the registry; it does not run every tool.

The initial implementation may connect to one MCP server while keeping tool names
globally unique. Shared tools can appear in several domain allowlists. Domain-
specific tools remain in the same registry until independent deployment, security,
or scaling requirements justify separate servers.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| Application | Validate the request, resolve the domain and MCP definitions, call the model, mediate allowed tool calls, enforce the attempt limit, record evidence, and coordinate review. |
| Domain | Own generation instructions, proposal schema, allowed MCP tool names, validation operations, deterministic finalization, and deterministic question expansion. |
| Model | Return the proposal and fixed check plan, request each check, and revise failed proposals using returned evidence. |
| Provider adapter | Translate provider-specific structured responses and tool calls into the shared model interface and parse against supplied schemas. |
| MCP | Expose authoritative tool definitions; invoke domain operations; enforce response deadlines and format structured evidence. |

The application contains no code-, mathematics-, or physics-specific checking
algorithm. Adding a provider changes only its adapter. Adding a domain supplies a
new domain module and appropriate MCP tools without adding domain branches to the
application loop.

The model selects checks using the domain prompt and MCP catalogue. No check is
automatically added. The domain still enforces finalization requirements: in the
code domain, missing execution-derived canonical answers or checked distractors
prevents a reusable artifact. A passing but insufficient plan returns `needs_review`;
it is not expanded or retried with new check membership.

Code operations live in `domains/code/validation_operations.py`. MCP wrappers in
`mcp/code_tools.py` supply dependencies and translate returned details or failures
into timed, versioned evidence. The operations can also be called directly without
an MCP client or server. Existing low-level algorithms remain in `domains/code/checks`.

## Checking an existing candidate

The `validate` command uses the same MCP discovery, dispatch, argument binding and
evidence handling as authoring. It requires a provider and model configuration.
The model returns a `CheckPlanResponse` containing only selected checks. The
application binds the supplied candidate, runs every selected check once, and
attempts domain finalization. It does not rewrite the candidate or automatically
add missing checks. A failed or insufficient plan returns `needs_review`.

The old `ValidationPipeline`, domain-built fixed plans, and automatic answer repair
and distractor fallbacks have been removed. Approval and durable version binding
remain Issue 39 work. This command checks a candidate; it does not approve it.

## Checking and correction

Before a call, the application rejects an unknown tool, a name outside the frozen
domain allowlist or fixed plan, malformed arguments, and a call after the attempt
limit. It also enforces deployment safety and resource limits. These checks protect
the execution boundary; they do not interpret domain correctness.

An attempt is complete after every tool in the fixed plan returns structured
evidence for the same proposal version. A successful transport call is not a passed
check: the application reads the tool result's `passed`, `failed`, or `error` state.
Any failure or error prevents technical success. Tool evidence should include
findings, checked values, actual scope, assurance method, tool version, duration,
and the proposal identity.

When all checks pass, the application marks the proposal checked. When anything
fails and attempts remain, it returns the complete attempt evidence to the model.
The model may revise proposal fields and arguments, but it cannot add, remove, or
replace checks. The full fixed plan then runs against the new proposal version.
After the third failed attempt, the application returns `needs_review`; it does not
pretend the evidence passed.

The initial architecture deliberately does not add an independent rule engine that
decides which checks the model omitted. Check-selection quality is measured with
reviewed evaluation fixtures in issues #40 and #56. Evidence from deterministic
correctness or safety tools remains authoritative and cannot be overridden by model
confidence or a heuristic quality score.

Incomplete conversations are bounded by `2 * plan_size + 2` tool turns per attempt;
exhausting that limit returns `error` with pending names and partial evidence. Invalid
arguments consume a selected check's unsuccessful slot; they can be revised in the
next attempt. Every selected name must have a terminal result, and no check can
execute twice in an attempt. Provider/MCP calls retain their configured deadlines.
Final results are sent back to the model; failure of that final acknowledgement is
recorded as `feedback_error` without discarding completed checking results.

## Finalization, review, and reuse

Domain finalization may package checked values into the reusable template and build
deterministic fields such as canonical answers or distractors. It must be a pure,
deterministic transformation and must not change the checked semantic content. If
that constraint proves unnecessary, finalization can be folded into application
artifact construction later without changing the model/MCP loop.

For code, finalization requires canonical answers and selected distractors returned
by a passing `code_validate_answers_and_distractors` call. A passing structure-only
plan returns `needs_review` with the successful attempt retained and no artifact.
Finalization never reruns the old validator or inserts answer/distractor repairs.

The planned review screen presents the exact artifact, original prompt and difficulty,
fixed plan, evidence history, limitations, and representative deterministic
questions. Approval and rejection are bound to its stable identity. Any material
revision creates a new version that requires fresh checks and approval.

Record the domain, prompt, difficulty, provider/model and settings, prompt/schema
versions, frozen catalogue, fixed plan, every proposal version and tool result,
tool versions, timings, artifact hash, and user decision. When source grounding is
added, also record immutable source and passage identifiers and citations. Never
store credentials or hidden model reasoning.

## Implementation order and completion criteria

1. Remove domain parser callbacks and parse provider responses generically against
   supplied schemas (#34).
2. Add the free-form request and combined proposal/check-plan contract (#35).
3. Expose authoritative MCP tools and structured evidence while preserving code
   execution limits (#36).
4. Resolve domain-allowed names to one frozen MCP catalogue snapshot and supply it
   to the model (#37).
5. Implement the application-mediated calls, fixed-plan retries, three-attempt
   limit, and `needs_review` result (#38).
6. Bind evidence and approval to a reproducible artifact and deterministic reuse
   path (#39).
7. Test the integrated workflow and run live provider/model evaluations (#40).

The [implementation issue list](../project-tracking.md#implementation-issues) records
the detailed acceptance criteria and dependencies. Tests must cover novel prompts,
all three difficulties, malformed model output, empty and unknown plans, invalid
tool arguments, unavailable tools, result errors, correction success, three failed
attempts, outdated evidence, exact artifact approval, and deterministic reuse.

## References

- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [GitHub Projects setup](../project-tracking.md)
