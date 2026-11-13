# Deterministic mathematics correctness

The `math_check_correctness` MCP tool and Python `check_math_correctness` function
check one structured mathematical answer. They use SymPy, closed expression
trees and resource-limited disposable workers. They make no model calls and do
not require a reusable authored check.

This is an additive interface. Historical math validation and private recipe
records retain their existing versions and behaviour. The new concrete tool is
marked `quality:math`, like the independent concrete code checks; it is not
silently inserted into the legacy template-planner catalogue. Both MCP tools use
only `quality:math`, not `domain:math`, so template authoring, relevance and
difficulty keep their existing wiring. Relevance and difficulty remain separate
from mathematical correctness.

## One result, specialised mathematics

Requests contain a `problem` and an `answer`. Problems select a mathematical
operation, not a curriculum topic or family. Expressions reuse the math IR's
`num`, `sym`, `param`, `op`, and `args` wire representation. Concrete requests
cannot contain unbound `param` nodes. Numbers are exact strings.

| Operations | Meaning of correctness |
| --- | --- |
| `evaluate`, `simplify`, `expand`, `factor`, `complete-square` | Mathematical equivalence on the problem domain |
| `differentiate` | Equivalence to the indicated derivative |
| `antiderivative` | Candidate derivative equals the integrand |
| `definite-integral` | Exact integral value within the supported real-domain scope |
| `solve` | Required complete solution set, or ordered unique linear-system solution |
| `matrix-multiply`, `determinant`, `inverse`, `lu` | Exact matrix calculations and defining identities |

With one solve target, `solve` requires the complete solution set on the declared
real, integer or rational domain. With multiple targets it supports only linear
equalities that determine one unique admissible tuple. Inconsistent,
underdetermined and parameterised systems are `unsupported`, not `incorrect`.

Answer-form checking and reusable check authoring are deferred. Answer form is
unassessed: an unchanged polynomial can pass an algebraic correctness request
even if it is not factorised or expanded. LU triangular and permutation structure
are part of a valid decomposition's mathematical definition. Worked prose is not
certified by checking a final mathematical answer.

### LU convention

An `lu` answer is checked against the row-permutation convention

```text
P * A = L * U
```

That is, `P` selects rows of the problem matrix `A`, `L` is unit lower
triangular and `U` is upper triangular. This is *not* scipy's `A = P * L * U`
convention with the transposed permutation. Because a three-cycle `P` differs
from its transpose, the two conventions only coincide for self-inverse
permutations such as a single swap; tests therefore use a three-cycle. Every LU
result reports the convention in `CorrectnessResult.details["lu_convention"]`.

Results distinguish `correct`, `incorrect`, `unknown`, `unsupported`, `timeout`,
and `error`. A well-formed answer with the wrong kind for the operation is
`unsupported`; an answer of the right kind whose mathematical values are wrong is
`incorrect`. One exception is deliberate: a candidate containing a provably
non-real subexpression on the declared domain, such as `sqrt(-1)**2`, is
`unsupported`, not `incorrect`. There is no real value to compare, so the checker
declines to make a correctness claim rather than calling the candidate wrong.
`unknown` does not mean incorrect. A timeout is a bounded execution
outcome, not a mathematical conclusion. Only `correct` maps to passing shared
`ToolEvidence`; `incorrect` maps to failed, while unresolved outcomes map to
error with their precise outcome retained in `details`.

## Concrete example

```python
from edcraft_validator.application.math_correctness import check_math_correctness

result = check_math_correctness({
    "problem": {
        "operation": "differentiate",
        "symbols": [{"name": "x"}],
        "variable": "x",
        "expression": {
            "op": "pow", "args": [{"sym": "x"}, {"num": "3"}]
        },
    },
    "answer": {
        "expression": {
            "op": "mul",
            "args": [
                {"num": "3"},
                {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
            ],
        },
    },
})
assert result.outcome == "correct"
```

For the MCP tool, send the same object in the `request` argument. Expressions,
ordered tuples, finite sets/unions of intervals, matrices, and LU decompositions
have distinct answer kinds. An empty `set` with no items/intervals denotes the
empty solution set; an interval with absent endpoints denotes unbounded ends.
Declared symbol domains (real, integer, rational) and `positive`, `nonzero` and
`integer` assumptions affect mathematical acceptance and are preserved through
computation. Relation givens are supported only by `solve`; for scalar operations
the public request validator rejects them as `unsupported`. Ordinary algebraic
cancellation must not silently erase excluded inputs.

Powers use SymPy's principal-power convention restricted to real inputs and
outputs. A fractional power requires a
nonnegative base (`base >= 0`), and a negative fractional exponent requires a
strictly positive base (`base > 0`); odd denominators do not change this rule.
Negative integer exponents require a nonzero base. No distinct signed real-root
operator is supported: `x**(1/3)` is defined only for `x >= 0`, not as a real cube
root of negative `x`. This interface therefore makes no claim about all real cube
roots, and problems needing that convention are outside scope.

## Adding an operation

Operation dispatch is a declarative registry in `engine/dispatch.py`:
`OPERATION_HANDLERS` maps every `Operation` literal to one handler with the
signature `(EngineContext) -> CorrectnessResult`, and `dispatch_operation` is
the only dispatcher. To add an operation:

1. Add the name to the `Operation` literal in `engine/contracts.py`.
2. Add a handler (or reuse `check_scalar`/`check_solutions`/`check_matrices`).
3. Add one entry to `OPERATION_HANDLERS`; a test asserts the registry covers the
   literal exactly.

Handlers raise `EngineUnsupported`/`EngineUnknown` for out-of-scope or unsettled
inputs; the dispatcher maps them to outcomes and stamps versions and duration.
Optional facts belong in `details` and must be deterministic (no set-order
leakage). The following `details` keys are reserved for a later answer-form
layer and are intentionally not implemented: `normalized_answer`,
`solution_set`, `factors`, `domain_assumptions`, `unknown_reason`.

## Property-based template qualification

`math_qualify_correctness_template` and Python `qualify_math_template` sample a
parameterised correctness request. Parameters can be bounded integer ranges or
explicit exact numeric values. A `param` node is substituted structurally in
both the problem and candidate; free text and arbitrary code are never executed.

```python
from edcraft_validator.application.math_correctness_sampling import qualify_math_template
from edcraft_validator.domains.math.engine.sampling import SamplingSettings

# template contains {"request": ..., "parameters": [
#     {"name": "a", "minimum": -1000000, "maximum": 1000000}
# ]}; the request uses {"param": "a"} leaves.
report = qualify_math_template(
    template,
    settings=SamplingSettings(max_examples=50, seed=42),
    timeout_seconds=30,
)
```

No Cartesian product is enumerated. `cases_checked` counts distinct sampled
assignments, not the size of the parameter domain. A passing report describes
sampled observations only. A campaign passes only when every observed outcome is
`correct`: one `incorrect` sample fails it, while any `unknown`, `unsupported`,
`timeout`, `error` or exhausted sampling budget makes it inconclusive. Unknown
never passes. Hypothesis may run additional trials while shrinking a failure; the
report retains the final counterexample. Seeds and Hypothesis/engine versions
support replay. Sampling is for qualification and bug finding; measuring
typical-input yield requires a separately chosen representative distribution. The
checker remains callable on every concrete answer a generation pipeline emits.

## Computational scope

The current scope uses up to eight declared symbols and matrix dimensions up to
eight. Matrix entries are exact numeric expressions. Powers require bounded
literal exponents, with magnitude and denominator at most twelve. Inputs have
literal length/bit limits, per-expression/global node limits, depth limits and
conservative intermediate-growth budgets. Expansion output is additionally
capped at 20,000 terms: the request validator estimates the expanded term count
before the worker starts, and equivalence operations re-count the actual expanded
candidate before any equivalence or counterexample work.

Estimation first applies a cheap structural normalisation: addition and
subtraction are flattened, structurally identical opposite terms are cancelled,
literal zero terms are dropped, multiplication is flattened and its literal ones
and zeros are removed, powers of zero and one are unwrapped, and `div(a, a)`
collapses to one. Division is then estimated multiplicatively (numerator terms
times denominator terms), while a power is bounded by the magnitude of its
integer exponent. Expressions that still contain a division or a
negative-integer power must also satisfy

```text
estimated_terms * (total_degree + 1) <= 20,000
```

where `total_degree` counts numerator plus denominator degree. Cancelling
structures that normalise to a small expression therefore pass, while nested
rational expansions with large numerators and denominators are rejected before
the worker starts. The normalisation is iterative, memoised and free of SymPy, so
adversarial trees stay bounded.

Default concrete timeout is ten seconds; Python callers can choose a finite
positive budget up to sixty seconds. Qualification has a separate worker deadline
and a bounded shrinking budget. Workers run in a fresh interpreter with a CPU
limit and a parent-side resident memory watchdog (default 1 GiB). The bootstrap
also reports the child's peak RSS (`ru_maxrss`) in its response envelope; a peak
above the cap is a memory error regardless of exit code, which covers workers
that allocate quickly and exit zero. The parent poll is a secondary guard for
long-running workers: on trigger it kills the child after rechecking the stop
flag and the child's pid identity, then raises. Linux also applies an
address-space limit, and macOS applies a best-effort data-segment limit while
preserving the inherited hard limit. If neither a pid handshake nor a kernel
limit is available, the parent fails closed with a distinct error instead of
running the worker unwatched. Exceeding the memory ceiling is never reported as
a passing check.

The operation enum is not a promise to decide every expression. Unsupported
structure, unsettled assumptions or symbolic sets, and exhausted budgets remain
explicit. Limits, eigenvalues, approximate-answer tolerances, proof assistants and
second-CAS fallback are outside this interface.

Unbounded trigonometric inequalities require a qualified periodic solver and
currently return `unsupported`. Nonsmooth differentiation and unsettled
multivariable domains may return `unknown`. Improper definite integrals,
including some convergent cases, remain outside the initial qualified scope.
Solution-set values/endpoints are closed exact expressions; symbolic candidate
values remain `unknown` even if cancellation hides their symbols.
