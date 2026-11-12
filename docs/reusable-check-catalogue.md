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
- **Actual-goal applicability.** Legacy polynomial/solve families derive their
  goal from their data. Version-3 templates also retain the validated requested
  `KernelGoal`; qualification and generation check each concrete problem against
  that goal using domain-owned mathematical metadata.
- **Independent evidence.** Qualification uses a separate oracle from the
  recipe operation. Property-based passes are sampled evidence, not proofs.
- **Immutable checks, additive templates.** Qualified checks are immutable and
  content-addressed. Version-1 templates and records keep their original bytes
  and hashes. Version-2 and version-3 templates pin the selected contract and
  exact check. New fields are omitted from old records' hashes when absent.
- **Bounded execution.** No Cartesian enumeration in the pilot path. Sampling,
  worker call counts, payload sizes and wall-clock time are bounded.

## Typed contracts

The developer-owned contracts live in
`edcraft_validator.application.check_pilot.contracts`.

| Contract id | Operation set | Relations | Degree | Answer | Mandatory policy |
| --- | --- | --- | --- | --- | --- |
| `polynomial.differentiate/1` | `polynomial-derivative/1` | `none` | 1 to 5 | expression | complete, independent, all options |
| `polynomial.equation-real/1` | `polynomial-solve-real/1` | `eq` | authoring 1 to 2; checks 0 to 2 | solution set | complete correctness and complete real set, independent, all options |
| `polynomial.inequality-real/1` | `polynomial-solve-real/1` | `lt`, `le`, `gt`, `ge` | authoring 1 to 2; checks 0 to 2 | solution set | complete correctness and complete real set, independent, all options |

Solve contracts deliberately keep `scope().min_degree == 0` so checks cover
constant boundary relations during independent qualification. Planning and
template authoring start at degree 1: model-facing descriptors advertise
`min_degree` 1 with a separate `check_min_degree` 0, and
`applicability_findings` rejects a degree-0 plan before any check or template
author call. No constant-question template is generated. Existing saved checks
with a degree-0 scope remain readable and applicable to degree 1–2 templates.

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

The registry in `kernel_registry.py` adds eleven contracts through the same
catalogue and `structured-check/1` operation set:

| Contract | Initial scope and correctness condition |
| --- | --- |
| `polynomial.antiderivative/1` | Rational polynomials, degree 0–5; differentiate the candidate, accept additive constants, distinguish one primitive from the general `+C` family |
| `polynomial.definite-integral/1` | Rational polynomials, degree 0–5; exact finite rational bounds and result, including equal/reversed bounds |
| `expression.differentiate/1` | Bounded arithmetic, integer powers, sin/cos/exp/log; complete first derivative with explicitly validated real-domain assumptions |
| `polynomial.expand/1` | Degree 1–5; exact equivalence and collected expanded form |
| `polynomial.factor/1` | Degree 1–2; exact equivalence and explicit irreducible factors over the rationals |
| `polynomial.complete-square/1` | Degree 2; exact equivalence and explicit `a*(x-h)^2+k` form |
| `linear-system.unique/1` | Nonsingular integer 2×2 systems; complete exact ordered `(x,y)` solution |
| `matrix.multiply/1` | Compatible rectangular matrices, dimensions 1–3; exact product |
| `matrix.determinant/1` | Exact 2×2/3×3 determinant |
| `matrix.inverse/1` | Nonsingular 2×2/3×3 matrices; both inverse products equal identity |
| `matrix.lu/1` | Exact 2×2/3×3 matrices; `P*A=L*U`, valid permutation, unit lower-triangular `L`, upper-triangular `U` |

The three owning modules are `calculus_checks.py`, `algebra_checks.py` and
`matrix_checks.py`. Each exposes closed problem/candidate validation, independent
expected-answer and candidate-checking algorithms, independently constructed
wrong answers, property strategies, rendering and `problem_extent`. The shared
workflow consumes that interface; it does not implement a second polynomial or
matrix interpreter. The registry rejects missing/duplicate contracts at startup.

Bounds are deliberate: algebra inputs have integer expanded coefficients of
absolute value at most 1000 and exact numeric leaves of absolute value at most
20. Systems use integer entries in `[-20,20]`. Calculus polynomial coefficients
have numerator magnitude at most 10000 and denominator at most 1000; integral
bounds have numerator magnitude/denominator at most 1000. Matrix entries have
numerator magnitude at most 1000 and denominator at most 100. Expression
differentiation uses at most 120 nodes, depth 16 and four declared real symbols;
log/division/negative powers require provable domain conditions. Algebra trees
use at most 80 nodes and depth 12. Intermediate exact arithmetic is bounded too.

An irreducible quadratic is already fully factored over the rationals. A
reducible expanded quadratic is rejected as a factorisation, even if equivalent.
These contracts validate final answers and required forms, not worked steps.

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

Standalone execution uses one trusted `ContractDescriptor.scope()`. The default
solve scope is the equation contract, so inequality execution must explicitly
select `polynomial.inequality-real/1`; differentiation uses its own default
contract. Compiled recipes retain the contract relation set, and execution
rejects a relation outside it (or data outside the degree/coefficient bounds)
before any solver runs. A scope error therefore returns error evidence, not a
mathematical verdict.

Structured recipes use `structured.expected(problem)` followed by
`structured.accepts(expected, problem, candidate)`. The candidate checker remains
independent of the expected-answer oracle and accepts valid alternative forms
within the contract. The `output` field names the verdict step, normally `out`.
The model-facing wire schema advertises exact argument names for each operation
and source-specific reference/literal shapes. Local validation and compilation
still enforce scope, types, references and policy before execution.

Each recipe invocation checks one candidate. The application handles question
sampling, parameter bindings, distractor generation and applying the recipe to
every option. Those delivery features are not operations the check author must
invent. Standalone structured MCP execution must name its trusted `contract_id`;
one stable executor serves all saved checks.

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

Version-3 templates use `pilot-template/3`, `KernelContractScope`, renderer
`structured-mcq/1`, a validated `goal` and one `StructuredProblemFamily`. The
family contains a closed concrete mathematical problem and numeric bindings;
the model chooses the mathematical structure rather than a question-family id.
For example, a matrix multiplication family can vary `left.0.0` over `[1,2,3]`.
Bindings preserve integer/exact-string types and cannot address metadata fields.

Family validation covers boundary and single-binding values without enumerating
the Cartesian product. Independent property-based qualification additionally
samples joint assignments. Every sampled/generated instance is checked against
the stored requested goal. A zero leading coefficient cannot silently turn an
exactly-quadratic request into a linear question. An out-of-goal generation case
fails the batch; passing sampled qualification does not prove all assignments.

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

1. Implement the closed problem/candidate types and kernel interface in the
   owning domain module, including semantic `problem_extent`, independent
   oracle/checker algorithms, negative cases and property strategies.
2. Register its descriptors/types and trusted bounds in `kernel_registry.py`.
   Extend closed goal/answer vocabularies only when genuinely needed. Reuse
   `structured-check/1` and the existing workflow for compatible capabilities.
3. Verify authoring, qualification, approval, generation, private saved reuse and
   stable MCP execution, including unsupported inputs and old-record replay.
4. Keep new mathematical primitives/types developer-reviewed. The LLM authors
   and saves recipes using registered operations; it cannot install new code.

Do not add a per-topic generator, a topic-to-contract lookup table, arbitrary
model-authored code, or an unsafe expression parser. If a request is outside the
registered contracts, return development-needed rather than inventing a task.
