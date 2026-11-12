# Reusable check-authoring pilot

Status: private, source-integrated pilot for univariate real-polynomial
differentiation. It is not a public sharing feature, and no deployment or
live-provider verification is claimed here.

## What the flow does

`edcraft_validator.application.check_pilot.CheckPilotApplication` is the public
Python facade. The backend owns authentication, provider/profile or BYOK
resolution, and HTTP error mapping; its `/ai-authoring/check-pilot` routes call
this facade. The AI-side flow is:

1. **Check authoring.** The check-author prompt receives trusted operation
   descriptors and may propose one closed recipe plus a title and explanation.
   The application compiles it against an allowlist of typed operations, then
   qualifies it with bounded property-based sampling.
2. **Qualification.** A passing recipe is saved as an immutable, content-addressed
   private check. Compile failures, failed qualification, exhausted repairs,
   provider failures and worker failures never become usable checks. Compilation
   rejections are recorded as an `error` qualification in the `compilation` phase
   with zero executions and no counterexample; they are not sampled false answers.
3. **Template authoring.** The template-author prompt proposes only a bounded
   coefficient-domain family. The application validates those domains before use
   and renders wording, answers and distractors itself.
4. **Reuse.** If the owner already has a passed check for the required scope and
   operation set, the check is reused (`reused_check=true`) and no check-author
   model call is made.
5. **Approval.** An educator explicitly approves a `ready` template using the
   current template and check digests. Rejection is separate from check
   qualification.
6. **Generation.** Seeded generation requires the matching approval and pinned
   digests. It makes no provider/model calls. Each emitted instance is guarded by
   application-owned correctness/distractor logic and the same pinned recipe.
   Sampling is bounded and deduplicated; a shortfall makes no claim that the
   declared domains are exhausted.

The HTTP contract is `POST /templates`, `GET /templates`,
`GET /templates/{template_id}`, `GET /checks`, `GET /checks/{check_id}`,
`POST /templates/{template_id}/approval` and
`POST /templates/{template_id}/generate`. Provider selection remains a backend
concern; the AI package accepts a resolved `ModelProvider`.

## Configured provider roles

The same resolved `ModelProvider` supplies two distinct structured prompt roles:

| Role | Prompt version | Output |
| --- | --- | --- |
| check-author | `check-author/1` | `CheckAuthorProposal`: trusted recipe, title, description, or development-needed result |
| template-author | `template-author/1` | `TemplateAuthorProposal`: bounded coefficient domains, or development-needed result |

No provider or model is hard-coded into the pilot. Model credentials are never
stored; provenance records safe provider/model identifiers, prompt versions,
request hashes and bounded provider settings. The backend selects the existing
configured profile or BYOK connection and closes it on every path.

## Qualification evidence and limits

Check qualification is property-based sampling, not a proof. The independent
expected derivative comes from coefficient arithmetic, not the same
differentiation call under test. Sampling covers labelled correct and incorrect
answers, alternate correct forms, explicit boundary polynomials and non-vacuous
semantic mutations. Weak always-true/always-false, identity and point-only
recipes are rejected by compilation. A separate held-out run uses a different
seed and salt and is not exposed to the author prompt.

Template qualification is separate evidence. It samples declared coefficient
domains, verifies rendered answers/distractors, and executes the pinned recipe.
No Cartesian enumeration occurs in the pilot path.

Defaults and bounds:

- Property-based examples: 50 default, 4 to 200.
- Execution calls: 1200 default, 1 to 10,000.
- Worker wall-clock timeout: 20 seconds default, at most 120 seconds.
- Check repairs: at most 2 after the initial proposal.
- Generated batch: quantity 1 to 100; at most 600 recipe cases per worker call.
- Recipe: at most 8 steps over the closed operation set.
- Family: degree 1 to 5, coefficient values in `[-20, 20]`, at most 10,000,000
  declared assignments; generation samples rather than enumerating them.
- Polynomial text: 200 characters and 120 tokens in the closed parser.

Results say "No counterexample found in sampled cases". Passed, failed,
inconclusive and error are distinct.

Each qualification carries a `phase`:

- `compilation` means the recipe was rejected before any case ran. Status is
  `error`, `execution_calls` is 0 and `counterexample` is `null`, so this is not a
  mathematical verdict about the recipe's semantics.
- `sampling` means bounded property cases ran. Sampled false answers remain
  `failed` with any shrunk counterexample preserved.

Older records without a `phase` are treated as sampling evidence. Compile
rejection still leaves the template at the high-level `needs_review` state with
bounded repair attempts, so an author can correct and resubmit it.

## Private immutable storage and reuse

Checks are stored per owner under a hashed owner directory and a content-addressed
`chk_.../v1.json` path. The stored check is revalidated against its content hash
on read; an immutable version is never overwritten. Templates are owner-scoped
records whose mutable approval uses an atomic compare-and-swap on the current
record hash. Approval and generation reject stale template/check digests.
Another owner cannot list, read, reuse, approve or generate these private
artifacts.

Reuse requires the same supported scope, operation set and a passed qualification.
A reused check still produces a new unreviewed template and requires its own
template qualification and approval.

## MCP adapter

`check_pilot_execute_recipe` is the one stable MCP adapter. It accepts a closed
recipe definition plus one bounded problem/candidate polynomial and returns tool
evidence. It uses the same recipe compiler and isolated executor as the
application. It has no owner or library parameter: owner resolution and library
access stay in the application, so a model-supplied owner string cannot grant
access.

## Isolated worker boundary

Both the existing math-validation worker and the pilot worker use
`edcraft_validator.tools.isolated_process` for JSON-only subprocess transport.
The selected worker module is an application-owned constant, never model input.
The parent applies one wall-clock timeout and maps non-zero exits, invalid JSON,
non-object responses and error envelopes to each caller's public exception type.

A tiny trusted bootstrap applies hard resource limits before importing the worker
module. The child environment is allowlisted to interpreter/runtime inputs such
as `PATH`, `PYTHONPATH`, locale and temporary-directory variables; provider and
database credentials are not inherited. `PYTHONUNBUFFERED=1` and
`PYTHONNOUSERSITE=1` are set. The request payload is capped at 8 MiB, which
covers supported 600-case batches.

Platform behavior:

- Linux: `RLIMIT_AS` bounds address space and `RLIMIT_CPU` bounds CPU time.
- Other POSIX systems, including macOS: `RLIMIT_CPU` is applied, but this path
  does not claim an enforced address-space limit. The parent wall-clock timeout
  and CPU limit still apply.
- The parent timeout is always authoritative. Limits never raise a tighter
  inherited soft or hard cap.
- No `preexec_fn` is used, so the boundary is safe to call from a threaded
  backend. A model can never supply arbitrary Python or shell text.

## Public Python facade

`CheckPilotApplication(root, *, qualification_settings=None)` exposes
`author_template`, `list_checks`, `get_check`, `list_templates`, `get_template`,
`decide` and `generate`. Methods return Pydantic models; use
`model_dump(mode="json")` on the wire. Safe exceptions are `PilotNotFound`,
`PilotConflict` and `PilotInputError`; callers map them to 404, 409 and 422.

## Local verification

Run focused tests with the worktree source on `PYTHONPATH` so workers import the
local implementation rather than an installed copy:

```bash
PYTHONPATH=/private/tmp/edcraft-check-pilot-worker-hardening/src \
  /private/tmp/edcraft-review-ai/.venv/bin/pytest -q tests/test_isolated_worker.py

PYTHONPATH=/private/tmp/edcraft-check-pilot-worker-hardening/src \
  /private/tmp/edcraft-review-ai/.venv/bin/pytest -q \
  tests/test_check_pilot_qualification.py \
  tests/test_check_pilot_template_qualification.py \
  tests/test_check_pilot_application.py \
  tests/test_check_pilot_storage.py \
  tests/test_check_pilot_author_schema.py \
  tests/test_math_validation.py tests/test_math_tool_errors.py \
  tests/test_mcp_server.py
```

Use `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
`uv run pytest` for the normal repository checks. Live provider tests are opt-in
and are not required to verify this pilot's local flow.

## Known limitations

- Property-based passes are sampled evidence, not universal correctness proof.
- The supported scope is deliberately narrow: univariate real polynomials in
  `x`, degree at most 5, bounded integer coefficients.
- macOS does not enforce the Linux address-space limit through this path; rely on
  the wall-clock and CPU limits there.
- This document does not claim public publication, deployment or live-model
  accuracy. The backend/frontend integration is source-based during local
  development; final dependency pinning is owned by the integration process.
