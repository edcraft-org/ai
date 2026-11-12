# Reusable check catalogue and authoring pilot

Status: private, source-integrated catalogue for reusable mathematics checks. The
fourteen trusted contracts cover bounded polynomial equations/inequalities,
algebraic forms, calculus, unique linear systems and exact matrix operations.
Checks are private. Provider experiments and deployment status are recorded
separately from this interface documentation.

## What the flow does

`edcraft_validator.application.check_pilot.CheckPilotApplication` is the public
Python facade. The backend owns authentication, provider/profile or BYOK
resolution, and HTTP error mapping; its `/ai-authoring/check-pilot` routes call
this facade. The AI-side flow is:

1. **Structured planning.** `check-planner/2` receives the trusted capability
   descriptors and the owner's qualified saved-check descriptors. It proposes a
   trusted `contract_id`, a structured `StructuredGoal`, and optionally one exact
   saved `CheckRef`. The application, not the model, validates the contract, goal
   and reference. If the reference is omitted, the application may select the
   newest applicable qualified check. An explicit unknown, foreign, stale or
   incompatible reference fails closed; it is never silently replaced with a
   different task.
2. **Check authoring when missing.** If no applicable saved check exists,
   `check-author/3` proposes one closed recipe from advertised versioned typed
   operations. The application compiles it against the contract's allowlist and
   qualifies it with independent bounded property-based sampling. A passing
   recipe is stored as an immutable, content-addressed private check.
3. **Template authoring.** `template-author/4` proposes only structured bounded
   coefficient domains for the selected contract. For differentiation it returns
   a `PolynomialFamily`; for equations or inequalities it returns a `SolveFamily`
   with the requested relation. The application validates the actual structured
   goal against both the plan and the pinned check scope. New contracts use a
   `StructuredProblemFamily`: a closed mathematical problem plus numeric-leaf
   bindings. Version-3 templates retain the validated requested goal, which is
   enforced for every sampled/generated instance using domain-owned metadata.
4. **Reuse.** A suitable saved check is reused (`reused_check=true`) and no
   check-author call is made. A new template remains unreviewed even when its
   check was reused.
5. **Approval.** An educator explicitly approves a `ready` template using the
   current template and check digests. Rejection is separate from check
   qualification.
6. **Generation.** Seeded generation requires the matching approval and pinned
   digests. It makes no provider/model calls. The whole batch — bounded sampling,
   key and distractor arithmetic, rendering, independent correctness guards and
   the pinned recipe checks — runs in one disposable JSON worker request. The
   parent validates owner storage, approval, pinned hashes, contract applicability
   and bounded structural/exact metadata. Symbolic execution and the complete
   question batch run in the worker. Sampling is bounded and deduplicated; a
   shortfall makes no claim that the declared domains are exhausted.

The HTTP contract is unchanged: `POST /templates`, `GET /templates`,
`GET /templates/{template_id}`, `GET /checks`, `GET /checks/{check_id}`,
`POST /templates/{template_id}/approval` and
`POST /templates/{template_id}/generate`. Provider selection remains a backend
concern; the AI package accepts a resolved `ModelProvider`.

## Trusted contracts

| Contract id | Task | Bounds |
| --- | --- | --- |
| `polynomial.differentiate/1` | Compare a complete candidate derivative with an independently derived polynomial | degree 1 to 5, integer coefficients in `[-20, 20]` |
| `polynomial.equation-real/1` | Compare the complete real solution set of `= 0` | template degree 1 to 2; check scope also covers constant degree 0, bounded integer coefficients |
| `polynomial.inequality-real/1` | Compare the complete real solution set of `<`, `<=`, `>`, `>=` | template degree 1 to 2; check scope also covers constant degree 0, bounded integer coefficients |

The planner and template author are advertised a minimum degree of 1, matching
the linear/quadratic families the renderer can generate. A degree-0 solve plan
is rejected before any check or template author call. The saved check scope keeps
a minimum of 0 because independent qualification intentionally samples constant
boundary relations; those boundary cases are check coverage, not generated
question templates.

There is no syllabus-topic dispatch. A topic-name request cannot by itself add a
capability. The eleven additional contracts and their explicit bounds are listed
in [`reusable-check-catalogue.md`](reusable-check-catalogue.md): polynomial
antiderivatives/definite integrals, broader differentiation, expansion,
factorisation, completing the square, unique 2×2 systems and matrix
multiplication/determinants/inverses/LU. Arbitrary integration, proofs and
unregistered operations still require developer work. New capabilities
are registered at the developer-owned contract/operation seam described in
[`reusable-check-catalogue.md`](reusable-check-catalogue.md).

Solve checks compare complete structured solution sets, not root substitution or
partial answers. Independent qualification covers repeated roots, no-real-root
cases, negative leading coefficients, empty/all-real outcomes, interval unions
and endpoint open/closed flags. It also includes constant degree-0 boundary
relations; this broadens check coverage only and does not add constant-question
generation.

## Configured provider roles

The same resolved `ModelProvider` supplies three distinct structured prompt roles:

| Role | Prompt version | Schema | Output |
| --- | --- | --- | --- |
| check-planner | `check-planner/2` | `check_plan` | `CheckPlanProposal`: contract, structured goal, reason, optional exact saved reference |
| check-author | `check-author/3` | `check_recipe` | `CheckAuthorProposal`: one-candidate mathematical validator, title and description |
| template-author | `template-author/4` | `polynomial_family` | `TemplateAuthorProposal`: polynomial/solve/structured family, or development-needed result |

A fresh flow calls planner, check author when needed, then template author. A
reuse flow calls planner then template author. No provider or model is
hard-coded into the pilot. Model credentials are never stored; provenance records
safe provider/model identifiers, prompt versions, request hashes and bounded
provider settings. The backend selects the existing configured profile or BYOK
connection and closes it on every path.

The roles separate mathematical validation from delivery. The check author does
not implement numeric bindings, MCQ assembly or option enumeration: the
application calls its single-candidate recipe on each option. Schema errors
consume the same bounded repair budgets as other authoring failures; transport
errors fail safely. Slow provider reasoning can dominate request time; the
existing provider settings, including `SOCLAAS_REASONING_EFFORT`, can be selected
for an experiment without changing mathematical qualification budgets.

## Selection metadata

New records expose optional additive `selection` metadata for the backend/UI:

```json
{
  "contract_id": "polynomial.inequality-real/1",
  "reason": "The request asks for a complete real inequality solution set.",
  "source": "saved",
  "check_ref": {"check_id": "chk_...", "version": "1", "sha256": "..."}
}
```

`source` is `saved` or `authored`; `check_ref` is the exact pinned qualified
check. Failed drafts may omit `selection` or store `null`. Ready version-2
templates require a matching selection.

## Qualification evidence and limits

Check qualification is property-based sampling, not a proof. The independent
expected answer comes from separate coefficient/discriminant/sign arithmetic,
recursive calculus rules and exact matrix algorithms rather than the candidate
checker under test. Wrong-answer construction does not consult the checker and
remove the false positives it is meant to expose. Sampling covers correct and
incorrect answers, alternate correct forms, explicit boundary cases and
non-vacuous mutations (missing root, extra root, flipped inequality, endpoint
flag changes). Weak always-true/always-false, identity and point-only recipes are
rejected by compilation. A separate held-out run uses a different seed and salt
and is not exposed to the author prompt.

Template qualification is separate evidence. It samples declared coefficient or
numeric-binding domains, verifies actual requested-goal constraints and rendered
answers/distractors, and executes the pinned recipe. No Cartesian enumeration
occurs in the pilot path.

Defaults and bounds:

- Property-based examples: 50 default, 4 to 200.
- Execution calls: 1200 default, 1 to 10,000.
- Worker wall-clock timeout: 20 seconds default, at most 120 seconds.
- Planner repairs: at most 2 after the initial proposal.
- Check repairs: at most 2 after the initial proposal.
- Template repairs: at most 2 after the initial proposal.
- Generated batch: quantity 1 to 100; at most 600 recipe cases per worker call.
  The generation worker has a 45-second wall-clock timeout, leaving margin inside
  the 60-second frontend generation budget and the 180-second backend request
  budget.
- Recipe: at most 8 steps over the closed operation set.
- Differentiation family: degree 1 to 5, coefficient values in `[-20, 20]`, at
  most 10,000,000 declared assignments; generation samples rather than
  enumerating them.
- Solve family: degree 1 to 2, one coefficient domain per exponent, nonzero
  leading domain, relation fixed by the plan.
- Polynomial text: 200 characters and 120 tokens in the closed parser. Structured
  solve payloads are bounded before parsing.

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

Saved-check reuse requires the same trusted contract and a stored scope that
covers the concrete structured goal, relation, degree bounds, coefficient bound,
answer type and mandatory policies. Legacy version-1 differentiation records
remain readable, keep their original bytes and hashes, and replay seeded batches
identically. They are never rewritten into version-2 records.

## MCP adapter

`check_pilot_execute_recipe` is the one stable MCP adapter. It accepts a closed
recipe definition plus one problem and candidate. Differentiation recipes accept
bounded polynomial text. Solve recipes accept one structured `PolynomialRelation`
and one structured `RealSolutionSet`. An optional `contract_id` selects the
trusted contract; differentiation defaults to its contract and solve defaults to
the equation contract, so inequality execution must explicitly name
`polynomial.inequality-real/1`. Compilation validates operation ids, versions,
argument/output types, step references and relation/scope applicability before
execution; an out-of-contract relation returns `RECIPE_INVALID` without a
mathematical verdict. It uses the same isolated executor as the application. It
has no owner or library parameter: owner resolution and library access stay in
the application, so a model-supplied owner string cannot grant access.

## Isolated worker boundary

Both the existing math-validation worker and the pilot worker use
`edcraft_validator.tools.isolated_process` for JSON-only subprocess transport.
The selected worker module is an application-owned constant, never model input.
The parent applies one wall-clock timeout and maps non-zero exits, invalid JSON,
non-object responses and error envelopes to each caller's public exception type.

Qualification, one-recipe MCP execution and whole-batch generation all cross this
boundary. A generation request carries the validated pinned template, recipe and
check reference plus the seed and quantity. The worker samples, renders, guards
and executes the pinned recipe for every key and distractor, then returns the
complete `PilotBatch` JSON. A timeout or error returns no partial batch; the
parent raises a safe conflict. Consequently the child wall-clock/CPU/address-space
limits cover the new symbolic generation path as well as recipe checking, and no
claim is made about symbolic generation work happening on the parent.

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
`decide` and `generate`. `find_applicable_check` is also exported for
application-owned lookup. Methods return Pydantic models; use
`model_dump(mode="json")` on the wire. Safe exceptions are `PilotNotFound`,
`PilotConflict` and `PilotInputError`; callers map them to 404, 409 and 422.

## Local verification

Run focused tests from the repository root with `src` on `PYTHONPATH` so workers
import the local implementation rather than an installed copy:

```bash
PYTHONPATH=src uv run pytest -q tests/test_isolated_worker.py

PYTHONPATH=src uv run pytest -q \
  tests/test_check_pilot_application.py \
  tests/test_check_pilot_author_schema.py \
  tests/test_check_pilot_boundaries.py \
  tests/test_check_pilot_catalogue.py \
  tests/test_check_pilot_compiler.py \
  tests/test_check_pilot_legacy_replay.py \
  tests/test_check_pilot_qualification.py \
  tests/test_check_pilot_solution_sets.py \
  tests/test_check_pilot_solve_flow.py \
  tests/test_check_pilot_storage.py \
  tests/test_check_pilot_template_qualification.py \
  tests/test_mcp_server.py
```

Use `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
`uv run pytest` for the normal repository checks. Live provider tests are opt-in
and are not required to verify this pilot's local flow.

## Known limitations

- Property-based passes are sampled evidence, not universal correctness proof.
- The supported scope is deliberately bounded: real univariate polynomials in
  `x`; differentiation to degree 5; equations and inequalities to degree 2.
- The independent solve oracle is limited to the documented linear/quadratic
  arithmetic; unsupported relations or higher degrees are development-needed.
- macOS does not enforce the Linux address-space limit through this path; rely on
  the wall-clock and CPU limits there.
- This document does not claim public publication, deployment or live-model
  accuracy. The backend/frontend integration is source-based during local
  development; final dependency pinning is owned by the integration process.
