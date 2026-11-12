# Reusable check catalogue: contracts and extension seam

This document describes the developer-owned seam behind the private check
catalogue. It complements
[`reusable-check-authoring-pilot.md`](reusable-check-authoring-pilot.md), which
covers the product flow, storage, provider roles and operational limits.

## Design invariants

- **No topic dispatch.** A request label never maps to a capability. The model
  proposes a trusted contract id and a structured goal; the application validates
  both. Unknown contracts and unsupported operations fail closed.
- **Closed data only.** Models return typed Pydantic data: `CheckPlanProposal`,
  `CheckAuthorProposal` and `TemplateAuthorProposal`. Model-authored Python is
  never executed. Recipes are compiled against a typed operation allowlist.
- **Exact references.** A saved-check reference is a `CheckRef` with check id,
  version and sha256. Unknown, foreign, stale, unqualified or incompatible
  references are rejected; they are never silently replaced.
- **Actual-goal applicability.** A template is checked against the structured
  goal derived from its own `PolynomialFamily` or `SolveFamily`, the selected
  plan, and the pinned check scope.
- **Independent evidence.** Qualification uses a separate oracle from the
  recipe operation. Property-based passes are sampled evidence, not proofs.
- **Immutable checks, additive templates.** Qualified checks are immutable and
  content-addressed. Version-1 templates and records keep their original bytes
  and hashes. New version-2 templates pin the selected contract and exact check.
- **Bounded execution.** No Cartesian enumeration in the pilot path. Sampling,
  worker call counts, payload sizes and wall-clock time are bounded.

## Typed contracts

The developer-owned contracts live in
`edcraft_validator.application.check_pilot.contracts`.

| Contract id | Operation set | Relations | Degree | Answer | Mandatory policy |
| --- | --- | --- | --- | --- | --- |
| `polynomial.differentiate/1` | `polynomial-derivative/1` | `none` | 1 to 5 | expression | complete, independent, all options |
| `polynomial.equation-real/1` | `polynomial-solve-real/1` | `eq` | 0 to 2 | solution set | complete correctness and complete real set, independent, all options |
| `polynomial.inequality-real/1` | `polynomial-solve-real/1` | `lt`, `le`, `gt`, `ge` | 0 to 2 | solution set | complete correctness and complete real set, independent, all options |

Each `ContractDescriptor` advertises a `scope()` (`ContractScope`) and a
model-facing `descriptor()`. `StructuredGoal` is the concrete task the planner
asks for. `applicability_findings` validates a goal against a contract;
`scope_applicability_findings` validates that a stored check scope covers a
concrete goal, including mandatory policies.

The planner interface is stable:

```python
CheckPlanProposal(
    supported=True,
    contract_id="polynomial.equation-real/1",
    goal=StructuredGoal(
        operation="solve",
        relation="eq",
        min_degree=1,
        max_degree=2,
        max_abs_coefficient=20,
        answer_type="solution_set",
        requires_complete_solution_set=True,
    ),
    reason="Solve the requested real equation completely.",
    saved_check_ref=None,
)
```

`saved_check_ref` may be `null`. If it is omitted, `resolve_plan` may choose an
applicable qualified saved check for the selected contract. If an explicit
reference is supplied, it must resolve exactly; otherwise the plan fails closed.

## Check catalogue

`edcraft_validator.application.check_pilot.catalogue` is application-owned:

- `qualified_check_descriptors(records)` returns compact model-facing
  descriptors for the newest qualified checks, bounded by
  `MAX_PLANNER_CHECKS`.
- `find_applicable_check(...)` returns the newest qualified check whose contract
  and scope cover the goal.
- `resolve_plan(...)` validates one `CheckPlanProposal`, resolves or fails a
  reference, and returns a `PlanResolution`.

The planner never receives another owner's records. Library access and owner
authorization stay outside the MCP adapter.

## Recipes and operations

`CheckRecipeDefinition` is a closed dataflow graph. Compilation in
`operations.py` validates:

- operation id and version against the allowlist;
- the operation set selected by the contract;
- exact argument names and value types;
- unique step ids and only prior-step references;
- the final verdict output and the required comparison shape.

Differentiation recipes must end in `poly.equivalent` comparing a prior
`poly.differentiate` result with the candidate polynomial. Solve recipes must end
in `set.equal` comparing a prior `relation.solve_real` result with the candidate
`RealSolutionSet`. Weak identity, point-sampling, constant-verdict and
number-comparison recipes are rejected.

The SymPy-backed recipe solver is separate from the independent oracle in
`solution_sets.py`. The oracle uses coefficient/discriminant/sign arithmetic and
handles repeated roots, negative leading coefficients, empty/all-real sets,
unions and open/closed endpoints. Candidate endpoints are parsed with a closed
grammar, not `eval` or `parse_expr`.

## Structured templates

Version-2 templates use `pilot-template/2` with a `ContractScope` and exactly one
family kind:

- differentiation: `family: PolynomialFamily`, renderer `polynomial-mcq/1`;
- equations/inequalities: `solve_family: SolveFamily`, renderer
  `polynomial-solve-mcq/1`.

`template_goal(definition)` derives the actual `StructuredGoal`, including the
exact family degree and the maximum absolute coefficient. The application checks
it against the plan and the pinned check scope before qualification. A model
cannot narrow the task, switch the relation, or claim complete-solution
correctness without the full set.

Generation samples assignments without building a Cartesian product. The whole
batch runs in one disposable worker request: every emitted correct key and
distractor is checked by the pinned recipe and by an independent guard before any
`PilotBatch` JSON is returned. Generated questions pin the exact check reference,
and the parent rejects a missing, mismatched or partial worker batch.

## Storage and compatibility

`PilotStore` validates check content hashes and template integrity on read.
Optional fields not present on old records are additive. `template_definition_sha256`
and `template_record_sha256` use `exclude_none=True` so version-1 raw record
bytes retain their original digests. Ready version-2 templates require a
`CheckSelection` that pins their check and names their contract.

`CheckSelection` is the agreed UI metadata:

```json
{
  "contract_id": "polynomial.differentiate/1",
  "reason": "The request asks for a complete derivative.",
  "source": "authored",
  "check_ref": {"check_id": "chk_...", "version": "1", "sha256": "..."}
}
```

## Adding a capability

Register a new capability at one seam:

1. Add a `ContractDescriptor` in `contracts.py` with its operation set,
   relations, degree/coefficient bounds, answer type and mandatory policies.
2. Add versioned operation descriptors in `operations.py`, or reuse an existing
   operation set where its semantics are genuinely shared. Add independent
   qualification strategies and a separate oracle where the mathematics is new.
3. Extend the structured template/family model and the trusted renderer/guard if
   the capability needs a new answer shape.
4. Add applicability, storage, generation, MCP and negative tests before wiring
   the product flow.

Do not add a per-topic generator, a topic-to-contract lookup table, arbitrary
model-authored code, or an unsafe expression parser. If a request is outside the
registered contracts, return development-needed rather than inventing a task.
