# Issue 38: code trace and recommended migration

Historical design proposal, 30 September 2026.
Implementation and results are recorded in [the delivery report](issue-38-results.md).
The implementation uses application-injected candidate arguments, as agreed after
this proposal, rather than requiring the model to resend the candidate.
 Traced against `origin/main` at `f7f1b3f`
(#63), after fetching origin. This document proposes changes; it does not claim
that the execution loop is implemented.

Sources: [Issue 38](https://github.com/edcraft-org/ai/issues/38),
[GOALS.md](../../GOALS.md), and the [agreed workflow](README.md).
The worktree is `agent-worktrees/issue-38`, branch `issue-38-architecture`.
Paths below are relative to this repository; line numbers refer to the traced base.

## Recommendation

Replace the authoring path's domain-selected `ValidationPipeline` with a bounded
conversation owned by `TemplateApplication`. Keep deterministic checking algorithms
inside MCP tools. The model chooses the check names once, requests their execution,
and revises a failed proposal using actual evidence. The application controls
permissions, proposal identity, completeness, and the three-attempt limit.

Free-form authoring is already implemented. The remaining architectural change is
who selects and invokes validation, how evidence returns to the model, and how
checked proposals become reusable artifacts. Do not rebuild the request layer or
remove the supported Python subset and finite input limits.

## 1. Current code trace

| Step | Code location | Actual behavior and implication |
| --- | --- | --- |
| 1. Read author request | `cli.py:114`, `CodeTemplateRequest` in `domains/code/code_schemas.py:56` | Resolves the domain, validates JSON or CLI fields, and creates the provider separately. Requires a free-form prompt and difficulty; distractor count defaults to three. There is no required authoring topic. |
| 2. Resolve tools | `application/template_workflow.py:43`, `mcp/catalogue.py:41` | Resolves domain-allowed names against one MCP listing before generation. Missing/duplicate definitions stop the job. `ToolCatalogueSnapshot` stores an immutable JSON copy. |
| 3. Build model context | `domains/code/prompt_builder.py:112`, `llm/tool_context.py` | Domain provides prompt/schema; application inserts the frozen catalogue. Tools are text context for planning, not callable provider tools yet. |
| 4. Generate once | `llm/openai_compatible_provider.py:45`, `llm/ollama_provider.py:27` | Adapters request structured JSON and parse the supplied Pydantic schema. Both consume only message content; neither returns native tool calls or maintains the required conversation. |
| 5. Parse plan | `llm/llm_contracts.py:12`, `:27`; `template_workflow.py:88` | Combined proposal/plan must be nonempty with unique names; application rejects names not offered. Arguments are deliberately a closed empty object, reserving real arguments for later turns. |
| 6. Build candidate | `domains/code/candidate_builder.py:15` | Deterministically copies proposal fields and request difficulty; derives a short template ID from request/proposal JSON. It does not run the selected checks. |
| 7. Ignore plan for execution | `template_workflow.py:105`, `domains/code/code_domain.py:92` | Application asks the domain to construct the old eight-check plan, context, and required-check policy. Model-selected names are only recorded in provenance. |
| 8. Run local checks | `validation/check_runner.py:21` | Calls Python check objects directly, skips inapplicable checks returning `None`, and stops at the first non-pass (`:74`). No MCP calls or correction turns occur. |
| 9. Finalize | `domains/code/code_domain.py:180` | Packages executor-derived answers and selected distractors from mutable validation context; removes the answer expression. Requires the old `ValidationReport`. |
| 10. Return artifact | `template_workflow.py:73`, `artifact_contracts.py` | Stores provider/model, original request, recommended checks, frozen catalogue, timestamp, and generation duration on successful artifacts only. No attempt history or `needs_review` result exists. |
| 11. Reuse | `cli.py:154`, `domains/code/question_generator.py:21` | Reads a validated artifact, verifies complete case coverage, uses stored canonical answers and deterministic seeded parameter selection. No AI/MCP call. Explicit human approval is not enforced by this CLI path yet. |

All source paths above start at `src/edcraft_validator/`.

The old eight checks are, in order:

1. `template_structure`: supported program structure and template contract.
2. `expression_safety`: parse answer and distractor expressions.
3. `answer_domain`: evaluate proposed answers over the finite Cartesian product.
4. `code_execution`: execute cases with the isolated tracing worker.
5. `canonical_answers`: derive actual answers; incorrect proposed answers may be
   promoted to distractors (`checks/answer_checks.py:47`).
6. `distractor_selection`: choose a globally valid subset; authoring may append
   generic fallback distractors (`checks/distractor_checks.py:29`).
7. `distractor_consistency`: check selected distractors against canonical answers.
8. `template_rendering`: verify rendering over the declared cases.

These checks share `CodeValidationContext`, so treating each old check as an
independent remote call would break their dependencies. The MCP tools already
provide better boundaries by creating their own context and running prerequisites.

## 2. What MCP already supplies

`mcp/server.py` registers three tools with strict input validation.
`mcp/code_tools.py` owns descriptions, inputs, implementations, and version `1.0.2`.

| Actual tool | Inputs | Evidence and limitations |
| --- | --- | --- |
| `code_verify_template_structure` (`:94`) | Complete candidate | Structure, expressions, proposed-answer domain, and rendering; does not prove execution answers. |
| `code_validate_answers_and_distractors` (`:141`) | Candidate, required distractor count | Executes the complete declared finite domain, rejects answer mismatches, selects only proposed distractors, returns canonical case answers and selected recipes. |
| `code_require_features` (`:236`) | Candidate, required feature list | Checks reachable syntactic features; does not establish pedagogical relevance or difficulty. |

The semantic tool calls shared canonical-answer code internally, but explicitly
fails on mismatch before returning success. Its context is a deep copy; it does
not repair the caller's proposal. Unlike the old authoring path, it adds no fallback
distractors. Preserve this behavior so failure evidence actually triggers correction.

`ToolEvidence` (`mcp/evidence.py:20`) has tool, version, `passed|failed|error`,
findings, details, and duration. Invalid arguments and unknown names can fail at
the MCP protocol boundary before this envelope exists; the application must handle
both protocol failures and structured unsuccessful results.

Keep existing technical bounds: at most 64 parameter combinations, restricted
Python/expressions, static-tool deadlines, isolated worker execution, per-case
timeouts, trace/resource limits. `_run_tool` bounds response time, but cancelling
its worker thread does not terminate synchronous work; process/deployment limits
remain necessary. MCP transport does not itself create a sandbox.

## 3. Target call flow

```mermaid
sequenceDiagram
    participant U as Author
    participant A as Application
    participant D as Domain
    participant P as Provider adapter / model
    participant M as MCP
    U->>A: Domain, free-form prompt, difficulty
    A->>D: Instructions, proposal schema, allowed names
    A->>M: List tool definitions once
    A->>P: Request + schema + frozen catalogue
    P-->>A: Proposal + nonempty fixed plan
    Note over A: Freeze plan membership and attempt candidate
    loop At most three complete attempts
        loop Every selected tool, once in this attempt
            P-->>A: Tool-call request and arguments
            Note over A: Validate name, arguments, identity and limits
            A->>M: Execute authorized call
            M-->>A: Structured evidence or protocol error
            A->>P: Actual result correlated to tool call
        end
        alt All selected checks passed
            Note over A: Return checked proposal and evidence
        else Failed and attempts remain
            P-->>A: Revised proposal; same plan membership
        else Third complete attempt failed
            A-->>U: needs_review + latest proposal + full history
        end
    end
    Note over A,D: Successful loop exits; pure finalization consumes evidence
```

“Deterministic validation” remains valuable: the model chooses which deterministic
tools to request. It never supplies the pass/fail verdict. MCP owns that verdict,
and the application checks whether every selected tool passed for the same candidate.

## 4. Recommended contracts and boundaries

### Provider conversation

Extend `ModelProvider` with a small provider-neutral turn contract alongside initial
structured generation. Represent assistant tool calls with a correlation ID, tool
name, and JSON arguments; represent tool results with that ID and actual evidence.
Allow correction turns to return a proposal parsed using the supplied domain schema.
Keep the transcript per job, not mutable shared state on a reusable provider.

Both adapters must preserve tool calls/results in subsequent messages. The current
`messages: list[dict[str, str]]` is too narrow for tool-call payloads. Keep wire-format
translation in adapters and policy in the application. Verify capabilities for each
configured provider/model; API compatibility alone does not establish support.
Use scripted providers for workflow tests before paid/live evaluation in #40.

Retain the initial combined response and empty planning arguments for compatibility.
Give execution calls their own argument contract validated against the frozen MCP
input schema. Do not broaden the initial schema to unchecked arbitrary dictionaries
or add a second domain-owned copy of each MCP input schema.

### Application loop

Add small explicit records (suggested names, not existing types):

- `ToolCallRequest`: call ID, name, JSON arguments.
- `CheckExecution`: attempt number, candidate digest, call ID, requested/effective
  arguments, and either actual MCP evidence or a distinct application/protocol error.
- `GenerationAttempt`: immutable proposal/candidate snapshot, executions, pending
  names, completion flag, timings, and outcome.
- `AuthoringResult`: `checked|needs_review|error`, latest proposal, frozen plan and
  catalogue, attempt history, and terminal reason.

`checked` means the selected plan passed, not user approval. Do not fabricate an MCP
tool version or successful evidence for an application error. Keep protocol and
infrastructure errors distinct from mathematical/code correctness failures.

The application should have no `if domain == "code"` correctness branch. Remove
`prepare_validation` and `ValidationPipeline` from model authoring. Keep the existing
manual `validate` command temporarily as an explicitly separate compatibility path;
its callers/tests mean deleting the runner globally in #38 is unnecessary. It must
never be an implicit fallback for the new authoring loop.

### MCP client

Extend or replace the listing-only `ToolCatalogue` adapter with a small client
boundary supporting list and call. Use one job-scoped connection for the first
implementation, with an async core and a single synchronous CLI boundary if needed.
Avoid invoking the current `asyncio.run()` listing method inside a running async loop.

Validate calls against frozen input schemas before dispatch and validate returned
structured content against the frozen output schema plus the shared evidence
contract. Reject mismatched tool identity/version and malformed evidence. Treat
missing result schemas as a configuration error for executable validation tools.
Do not infer success from nonempty text or transport success. Freeze definitions,
but also verify tool versions at execution: a cached catalogue does not pin a remote
implementation. Do not silently refresh definitions halfway through retries.

### Bind evidence to the proposal actually under review

Current tool inputs accept an entire candidate supplied by the caller. A model
could submit an easier or older candidate in its arguments while the application
mistakenly associates the result with the current proposal. Name allowlisting and
JSON Schema validation do not prevent that substitution.

Recommended minimal contract: the domain exposes a pure argument-binding hook that
checks the candidate equals the current canonical candidate and that request-owned
values (such as `required_distractors`) equal the original request. Reject mismatches;
do not silently overwrite them. Model-owned arguments, such as a feature list, remain
schema-checked and can be revised between attempts. This hook binds identities and
request constraints; it neither chooses checks nor runs correctness algorithms.

Assign an application-owned digest to the full canonical candidate and record it
on each attempt and execution. Deep-copy or serialize snapshots: a frozen Pydantic
outer object does not make nested lists/dictionaries immutable. The existing short
template ID is not sufficient evidence of the final artifact's identity after
distractor selection; #39 must bind that separately.

## 5. Loop rules and failure semantics

1. Resolve the allowlist/catalogue once. Validate the first response, reject empty,
   duplicate, or unoffered plan names, and freeze membership.
2. Freeze one candidate per attempt. Accept only calls in both the frozen allowlist
   and plan. A name already completed in this attempt cannot execute again.
3. Validate and bind arguments before dispatch. Execute legitimate requests even
   after another selected check fails; the old fail-fast runner cannot be reused.
4. Record a terminal result for every selected name. A dispatch/schema/transport
   error is a non-pass; never claim that the tool ran when dispatch failed. Only
   actual execution can supply tool evidence. Return the actual results to the model.
5. Technical success requires exactly the whole plan with all results passed for
   this attempt's candidate. Never combine attempt 1's passing structure evidence
   with attempt 2's passing execution evidence.
6. After complete failure, ask for a revised proposal and tool arguments, preserving
   check membership. Even unchanged proposals must rerun the full plan. No proposal
   replacement during an active attempt and no new check after a failure.
7. On the third complete failure, return `needs_review`, the latest proposal, and
   all three attempts. Never return a `ValidatedCodeTemplate` on this path.

Issue 38 specifies complete attempts but not indefinite malformed conversations.
Recommended explicit policy: a per-attempt turn bound (initially `2 * plan_size + 2`)
plus provider/call/job deadlines. Reject out-of-plan calls without dispatch and give
bounded corrective feedback. If the model omits checks, repeatedly requests duplicates,
changes plan membership, or never produces a valid revision, terminate as `error`
with partial history and pending names. Do not count an incomplete conversation as
three completed attempts or auto-run checks the model never requested. The bound is
a proposed operational default to calibrate, not an existing issue requirement.

An invalid request for a selected name consumes that name's unsuccessful slot for
the attempt; arguments can be corrected in the next attempt. Transport retries must
not invisibly execute a check twice. Initially record uncertain execution as an error
instead of automatically redispatching it. Provider HTTP retries are distinct from
the three proposal attempts and must not reset that budget.

## 6. Finalization is the main design seam

`CodeDomain.finalize_template(context, report)` currently depends on values computed
by the old pipeline. Do not rerun that pipeline merely to populate those values:
doing so would restore a hidden deterministic check plan and duplicate execution.

Recommend a pure finalizer consuming the accepted candidate and current-attempt MCP
evidence. The semantic tool already returns `canonical_answers` and
`selected_distractors`. Package those checked outputs without executing code, adding
fallbacks, or reinterpreting a failed proposal as passed. Verify complete case
coverage and that selected recipes belong to the checked proposal; preserve the
original proposal alongside the derived artifact. Evidence types must bridge the
old `ValidationEvidence` and new `ToolEvidence` without losing error/scope information.

There is a real gap between these two claims:

- Every check the model selected passed.
- Enough evidence exists to construct an exhaustively validated, reusable MCQ.

A plan containing only `code_require_features` can satisfy the first claim while
providing no canonical answers. The agreed workflow deliberately excludes an
independent missing-check rule engine. Therefore return a checked proposal from #38,
and have domain finalization explicitly report missing artifact data rather than
inventing answers or silently running extra tools. Expose that as non-reusable and
requiring review; retain the successful plan outcome separately. Evaluate the omitted
semantic tool as a selection-quality problem in #40. This makes the gap visible
without making the domain secretly choose the model's plan.

#38 needs the result/evidence boundary now; #39 owns durable provenance, artifact
identity and the deterministic reuse integration. Keep `generate` accepting only
proper reusable artifacts. Human approval remains a distinct lifecycle requirement,
not a consequence of `checked`. Do not imply that the current CLI enforces approval.

## 7. Implementation slices

| Order | Files / areas | Deliverable |
| --- | --- | --- |
| 1 | `llm/llm_contracts.py`, application result contracts | Native-call-neutral messages, immutable attempt records, fixed-plan and result types. Keep initial planning compatibility. |
| 2 | Both provider adapters | Normalize tool requests, correlate results, retain conversation, parse revisions generically. Add adapter tests for empty/malformed/multiple calls and unsupported capabilities. |
| 3 | `mcp/catalogue.py` and a small client module | Job-scoped list/call, frozen-schema checks, structured evidence/error normalization, deadlines and version checks. |
| 4 | `application/template_workflow.py` | Bounded three-attempt loop, complete plan execution, feedback, terminal results; no old runner in authoring. Test with a non-code fake domain. |
| 5 | `domains/domain_contract.py`, code domain, prompt builder | Pure candidate binding and evidence-based finalization boundary. Remove promises of automatic answer/fallback repair from prompts and bump prompt version. |
| 6 | `cli.py`, `template_evaluator.py`, artifact contracts | Serialize non-success results/history, distinguish evaluation jobs from correction attempts, preserve evidence, and use a documented nonzero CLI outcome when review/error remains. |
| 7 | #39 / #40 integration | Durable artifact provenance/reuse and live provider evaluation. Keep approval UI, difficulty estimation, new domains and retrieval outside #38. |

Migrate callers to an accurately named method such as `author_template()` returning
`AuthoringResult`; `create_validated_template()` cannot truthfully describe every
possible outcome. If temporarily retained, its wrapper must reject non-reusable
outcomes explicitly rather than discarding their evidence.

## 8. Verification plan

| Invariant | Required test |
| --- | --- |
| Real model-directed dispatch | Scripted model requests tools; actual in-process FastMCP server receives exactly those calls. Listing and planning alone execute nothing. |
| Fixed membership and permissions | Unknown, unoffered, allowed-but-unselected, duplicate and added/removed checks never reach MCP. Catalogue is listed once across all retries. |
| Complete attempts | First selected check fails; every remaining selected check still gets a result. A model omitting a check cannot pass. |
| Same-candidate evidence | Reject substituted candidates, weakened request-owned arguments and stale results. No evidence mixing across attempts. |
| Correction | Fail then pass uses a revised proposal and fresh full-plan results; success exits immediately. Three failures return latest proposal plus full history and no fourth attempt. |
| Fail closed | Invalid input/result schemas, unavailable tool, protocol error, timeout, wrong tool/version, malformed model output and exhausted conversation bounds never pass. |
| Deterministic ownership | Wrong proposed answers and insufficient distractors reach the model as failures; finalization never calls the old runner, provider or executor. |
| Selection versus reuse | A structure-only successful plan is recorded honestly but cannot produce a reusable artifact with fabricated answers. |
| Provider/domain independence | Exercise both adapters and a fake non-code domain; application contains no Python correctness logic. |
| Retained limits/reuse | Existing safety, worker and finite-domain tests stay intact; seeded question expansion makes zero AI/MCP calls. |

Focused baseline run on 30 September 2026: **79 passed** in 3.17 seconds:

```sh
PYTHONPATH=src ../../ai/.venv/bin/python -m pytest -q \
  tests/test_template_workflow.py tests/test_mcp_server.py \
  tests/test_tool_catalogue.py tests/test_code_template_request.py \
  tests/test_openai_compatible_provider.py tests/test_ollama_provider.py
```

This verifies the traced existing behavior, not the proposed loop. Tests use stubs
and in-process MCP; no live provider evaluation was performed. The existing venv
supplied dependencies and `PYTHONPATH=src` selected this worktree's application code.

## 9. Documentation corrections to make with implementation

- The workflow's illustrative tools (`code_verify_execution_answers`,
  `code_require_feature`, `code_check_distractors`, `code_assess_difficulty`) are not
  the live three-tool catalogue. Replace examples with executable names/arguments;
  difficulty assessment remains planned work.
- Use `beginner|intermediate|advanced` consistently. The GitHub milestone description
  still mentions `easy|medium|hard`; GOALS.md and current schemas agree on the former.
- Keep GOALS.md's target and historical evidence separate. Record #38 as complete
  only after the application-mediated loop and failure semantics pass their tests.
- Explain that model-selected feature arguments can become less demanding across
  retries even when tool names stay fixed. Preserve both argument versions and the
  original prompt for selection/relevance evaluation; frozen names alone do not
  prove equivalent pedagogical coverage. Do not add an unstated semantic rule engine.
