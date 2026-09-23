# Template generation workflow

Status: agreed target design before implementation, 23 September 2026.
This document and [the sequence diagram](generate-template.puml) define the target
workflow. The code on this documentation branch still implements the earlier
workflow. Product scope and milestone order are in [GOALS.md](../../GOALS.md).

## Decisions

1. Every request contains a domain, a free-form prompt, and a required `easy`,
   `medium`, or `hard` difficulty. Provider and model remain separate configuration.
2. The selected domain supplies generation instructions, a proposal schema, and the
   names of MCP tools allowed for that domain.
3. MCP is authoritative for each tool's description, input and result schemas, and
   implementation. The application resolves the domain's names against MCP and
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
checks, MCP tools own domain-specific validation algorithms, and the model owns
check selection and correction. Provider-managed MCP execution is outside the
initial scope because the application must preserve permissions, limits, evidence,
and consistent behavior across local and hosted models.

## Request and response

The public authoring request is:

```json
{
  "domain": "code",
  "prompt": "Create a Python MCQ about summing even numbers in a list. Use a loop and include accumulator mistakes as distractors.",
  "difficulty": "medium"
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
    "code_verify_execution_answers",
    "code_require_feature",
    "code_check_distractors",
    "code_assess_difficulty"
  ]
}
```

The application resolves those names to current MCP descriptions and schemas and
sends them with the prompt, difficulty, instructions, and proposal schema. The
model's first response contains the proposal and a nonempty fixed check plan:

```json
{
  "proposal": {
    "question_text": "What value is printed?",
    "code": "...",
    "parameters": {"values": [[1, 2, 4], [3, 6, 7]]},
    "answer_kind": "integer"
  },
  "checks": [
    {"name": "code_verify_execution_answers", "arguments": {}},
    {"name": "code_require_feature", "arguments": {"feature": "loop"}},
    {"name": "code_check_distractors", "arguments": {}},
    {"name": "code_assess_difficulty", "arguments": {"requested": "medium"}}
  ]
}
```

This is one proposal-and-planning response. It does not mean that the model executes
tools inside that response. Subsequent model turns request calls and receive the
actual evidence. Provider adapters normalize native tool-call formats into the
shared application representation. Domains supply schemas and never supply parser
callbacks.

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
| Domain | Own generation instructions, proposal schema, allowed MCP tool names, deterministic finalization, and deterministic question expansion. |
| Model | Return the proposal and fixed check plan, request each check, and revise failed proposals using returned evidence. |
| Provider adapter | Translate provider-specific structured responses and tool calls into the shared model interface and parse against supplied schemas. |
| MCP | Own authoritative tool definitions, deterministic implementations, technical limits, and structured evidence. |

The application contains no code-, mathematics-, or physics-specific checking
algorithm. Adding a provider changes only its adapter. Adding a domain supplies a
new domain module and appropriate MCP tools without adding domain branches to the
application loop.

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

## Finalization, review, and reuse

Domain finalization may package checked values into the reusable template and build
deterministic fields such as canonical answers or distractors. It must be a pure,
deterministic transformation and must not change the checked semantic content. If
that constraint proves unnecessary, finalization can be folded into application
artifact construction later without changing the model/MCP loop.

The review screen presents the exact artifact, original prompt and difficulty,
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
