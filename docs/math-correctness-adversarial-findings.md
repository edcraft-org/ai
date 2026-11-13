# Maths-correctness adversarial findings

Scope: deterministic maths engine, correctness outcomes only. The harness
mutates valid requests in two directions: meaning-preserving edits must never
produce `incorrect`, and meaning-changing edits must never produce `correct`.
All work was done on `codex/dme-adversarial`; no engine source or existing test
was changed.

## Outcome summary

| Family | Cases | `correct` | `incorrect` | `unknown` | other |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base requests | 17 | 17 | 0 | 0 | 0 |
| Preserving mutations | 87 | 87 | 0 | 0 | 0 |
| Breaking mutations | 49 | 0 | 49 | 0 | 0 |

The base set covers every supported operation: evaluate, simplify, expand,
factor, complete-square, differentiate, antiderivative, definite-integral,
solve (quadratic, closed/open inequality, 2x2 linear system), matrix-multiply,
determinant, inverse and LU.

## Defects

### D-complex-undefined — critical (false `correct`)

A candidate answer may cancel a finite but **non-real** subexpression. The
matrix and solution handlers inspect only the final compiled value, so
`sqrt(-1)**2` is erased to `-1` and accepted even though no real value is
assigned to `sqrt(-1)`.

Affected code:

- `src/edcraft_validator/domains/math/engine/context.py:34` rejects only
  `is_finite is False` or `nan`, never `is_real is False`.
- `src/edcraft_validator/domains/math/engine/matrices.py:410-417`
  (`_candidate_entries_are_finite_real` / `_definitely_not_finite_real`)
  checks the final cell value, not its subexpressions.
- `src/edcraft_validator/domains/math/engine/matrices.py:138,374`
  (`_has_raw_symbol`) rejects symbols, but not undefined non-real constants.
- `src/edcraft_validator/domains/math/engine/solutions.py:272-285`
  (`_validate_number`) likewise checks only the final solution value.
- The scalar handler does not have this hole because it derives domain guards
  from the original AST (`conditions.py:75-88`) and rejects the candidate on
  domain coverage (`scalar.py:115-153`).

Minimal reproducer (determinant):

```python
from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest
from edcraft_validator.domains.math.engine.dispatch import check_in_process


def n(value):
    return {"num": str(value)}


request = {
    "problem": {
        "operation": "determinant",
        "matrix": [[n(-1), n(0)], [n(0), n(1)]],
    },
    "answer": {
        "kind": "expression",
        "expression": {
            "op": "pow",
            "args": [{"op": "sqrt", "args": [n(-1)]}, n(2)],
        },
    },
}
print(check_in_process(CorrectnessRequest.model_validate(request)).outcome)
# observed: correct
# expected: unsupported / incorrect / unknown (not correct)
```

Minimal reproducer (solve):

```python
request = {
    "problem": {
        "operation": "solve",
        "symbols": [{"name": "x"}],
        "relations": [{"kind": "eq", "lhs": {"sym": "x"}, "rhs": n(-1)}],
        "solve_for": ["x"],
    },
    "answer": {
        "kind": "set",
        "items": [{"op": "pow", "args": [{"op": "sqrt", "args": [n(-1)]}, n(2)]}],
    },
}
print(check_in_process(CorrectnessRequest.model_validate(request)).outcome)
# observed: correct
```

The same acceptance was reproduced for `matrix-multiply`, `inverse`, `lu` and a
linear-system tuple (six cases, all xfailed in
`tests/test_math_correctness_adversarial.py`).

Impact: the simplified numeric value is right, but the candidate expression is
undefined on the real domain. This is a false `correct` under the engine's own
real-domain contract, so it is recorded as critical. A checker that only wants
the residual value may consider this a definedness-only issue.

Existing-test status: **not caught**.
`tests/test_math_correctness_regressions.py::test_numeric_matrix_candidate_cannot_cancel_an_undefined_subexpression`
and `test_candidate_root_expression_must_be_defined_before_cancellation` use
`(1/0)**0`; that subexpression is non-finite and is rejected by
`context.py:34`. No existing test uses a finite non-real intermediate such as
`sqrt(-1)**2`.

## Preserving-mutation coverage gaps

No preserving mutation produced `unknown` or `incorrect`. The table below is
therefore empty apart from the per-operation denominators; the required rate is
0/87 = 0.0%.

| Operation | Preserving cases | Preserving `unknown` | Rate | Breaking cases | Breaking `unknown` |
| --- | ---: | ---: | ---: | ---: | ---: |
| evaluate | 10 | 0 | 0.0% | 4 | 0 |
| simplify | 6 | 0 | 0.0% | 2 | 0 |
| expand | 6 | 0 | 0.0% | 2 | 0 |
| factor | 6 | 0 | 0.0% | 2 | 0 |
| complete-square | 7 | 0 | 0.0% | 2 | 0 |
| differentiate | 4 | 0 | 0.0% | 3 | 0 |
| antiderivative | 5 | 0 | 0.0% | 2 | 0 |
| definite-integral | 5 | 0 | 0.0% | 3 | 0 |
| solve | 21 | 0 | 0.0% | 16 | 0 |
| matrix-multiply | 4 | 0 | 0.0% | 3 | 0 |
| determinant | 4 | 0 | 0.0% | 2 | 0 |
| inverse | 4 | 0 | 0.0% | 3 | 0 |
| lu | 5 | 0 | 0.0% | 5 | 0 |
| **Total** | **87** | **0** | **0.0%** | **49** | **0** |

## Non-correctness observation

`validate_request` accepts any expression up to 200 nodes. A fixed-seed
150-node tree of `add`/`sub`/`sin`/`cos` nodes (generator
`_safe_sum_tree`, seed `20261113`) was accepted and exceeded 30 seconds in
`check_in_process` on this machine. The public facade's 10-second worker
timeout converts that to `timeout`, so it is not a wrong verdict; this is a
resource-boundedness gap, severity **low**, outside the correctness defect
list. The committed fuzz test therefore uses only trees above the 200-node
budget (all rejected before SymPy) plus a 20-node accepted tree for the
bounded branch.

## Verification

Commands run in the worktree:

```text
uv run pytest tests/test_math_correctness_adversarial.py -q
# 177 passed, 6 xfailed
uv run ruff check tests/_math_mutations.py tests/test_math_correctness_adversarial.py
# All checks passed
uv run ruff format --check tests/_math_mutations.py tests/test_math_correctness_adversarial.py
# clean
```
