# Deterministic mathematics correctness

The `math_check_correctness` MCP tool and Python `check_math_correctness` function
check one structured mathematical answer. They use SymPy, closed expression
trees and resource-limited disposable workers. They make no model calls and do
not require a reusable authored check.

This is an additive interface. Historical math validation and private recipe
records retain their existing versions and behaviour. The new concrete tool is
marked `quality:math`, like the independent concrete code checks; it is not
silently inserted into the legacy template-planner catalogue.

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

Answer form is unassessed: an unchanged polynomial can pass an algebraic
correctness request even if it is not factorised or expanded. LU triangular and
permutation structure are part of a valid decomposition's mathematical
definition. Relevance and difficulty are separate assessments. Worked prose is
not certified by checking a final mathematical answer.

Results distinguish `correct`, `incorrect`, `unknown`, `unsupported`, `timeout`,
and `error`. `unknown` does not mean incorrect. A timeout is a bounded execution
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
Domains and symbol assumptions affect mathematical acceptance and are preserved
through computation. Ordinary algebraic cancellation must not silently erase
excluded inputs.

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

No Cartesian product is enumerated. A passing report describes sampled
observations only. Hypothesis may run additional trials while shrinking a
failure; the report counts distinct evaluated assignments and retains the final
counterexample. Unresolved results produce an inconclusive campaign, not a pass.
Seeds and Hypothesis/engine versions support replay. Sampling is for qualification
and bug finding; measuring typical-input yield requires a separately chosen
representative distribution. The checker remains callable on every concrete
answer a generation pipeline emits.

## Computational scope

The current scope uses up to eight declared symbols and matrix dimensions up to
eight. Matrix entries are exact numeric expressions. Powers require bounded
literal exponents, with magnitude and denominator at most twelve. Inputs have
literal length/bit limits, per-expression/global node limits, depth limits and
conservative intermediate-growth budgets. Default concrete timeout is ten
seconds; Python callers can choose a finite positive budget up to sixty seconds.
Qualification has a separate worker deadline and a bounded shrinking budget.

The operation enum is not a promise to decide every expression. Unsupported
structure, unsettled assumptions or symbolic sets, and exhausted budgets remain
explicit. Limits, eigenvalues, approximate-answer tolerances, proof assistants,
second-CAS fallback and reusable check authoring are outside this interface.
