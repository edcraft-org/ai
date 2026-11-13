# Math correctness coverage

`tests/test_math_correctness_corpus.py` is a golden corpus of 178 complete
requests for the deterministic mathematics engine. Each case names one contract,
supplies a problem and a candidate answer, and asserts one exact outcome. The
corpus mixes accepted answers, definite mistakes, and correct-by-design refusals:
`unknown` and `unsupported` are mathematical statements about scope, not
failures to decide.

Run it with:

```sh
uv run pytest -q tests/test_math_correctness_corpus.py
```

The companion sweep is `uv run pytest -q tests/test_math_correctness_*.py`.

## Corpus by contract

| Contract | Cases | Accepted when | Correct-by-design refusals | Known gaps |
| --- | --- | --- | --- | --- |
| `antiderivative` | 14 | The candidate differentiates exactly to the integrand on the integrand's whole real domain; additive constants, including a declared symbolic constant, are free. | A primitive that misses a branch of the source domain (`log(x)` for `1/x`) is `incorrect`, not refused. | Primitives needing special functions or piecewise branch choices are outside scope. |
| `complete-square` | 11 | Algebraically equivalent to the source on its domain; no vertex form is required. | Wrong constants or scales are `incorrect`. | Form, presentation and step validity are not assessed. |
| `definite-integral` | 13 | The exact value equals the candidate; reversed bounds negate and equal bounds give zero. | Symbolic endpoints are `unsupported`. Interior poles and endpoint singularities (improper integrals) are `unknown`. | Some convergent improper integrals remain outside the qualified scope; piecewise-conditional values are `unknown`. |
| `differentiate` | 14 | The candidate is exactly the indicated derivative on the differentiability domain, including higher orders. | A candidate that introduces a singularity is `incorrect`. | Nonsmooth points (for example `abs` at a cusp) may return `unknown`. |
| `expand` | 13 | Algebraically equivalent to the source on its domain. | A missing cross term or constant is `incorrect`. | Answer form is not assessed: a factored answer passes `expand`. |
| `factor` | 12 | Algebraically equivalent to the source on its domain. | A wrong root or multiplicity is `incorrect`. | Answer form is not assessed: an expanded answer passes `factor`, and an irreducible expression may be returned unchanged. |
| `determinant` | 14 | Exact determinant, including `1x1`, rational, radical, singular and `5x5` matrices. | A non-expression answer or a non-square matrix is `unsupported`. | Symbolic matrix entries are `unsupported` before cancellation. |
| `inverse` | 14 | Both exact products `A*A^-1` and `A^-1*A` equal the identity. | A singular matrix, a non-matrix answer or a non-square matrix is `unsupported`. | Symbolic entries are outside scope; numerical approximations are not used. |
| `lu` | 13 | `P` is a permutation, `L` is unit lower triangular, `U` is upper triangular, and `P*A = L*U`. Alternative pivots and a `3`-cycle permutation are accepted. | A non-permutation `P`, non-unit `L`, non-triangular factor, wrong shape or `L*U != P*A` is `incorrect`. A non-square matrix is `unsupported`. | Decomposition uniqueness is not required; any valid decomposition is accepted. |
| `matrix-multiply` | 14 | Exact product of the declared dimensions, including rectangular, outer and `8x8` products. | Mismatched inner dimensions or a non-matrix answer is `unsupported`; a wrong shape or entry is `incorrect`. | Symbolic entries are outside scope. |
| `solve` (one variable) | 29 | The answer set equals the complete solution set on the declared real, integer or rational domain. Open/closed intervals, finite unions, the empty set, all reals, `ne` exclusions, extraneous radical/rational roots, and `abs`/`exp`/`log` equations are covered. | Periodic non-`ne` source domains (for example `log(sin(x))`) are `unknown`; unrepresentable periodic solution sets are `unsupported`. | Periodic solution sets, some irrational boundary intersections and unsettled symbolic sets remain `unknown`. |
| `solve-linear-system` | 17 | One unique admissible ordered tuple satisfying every original equation; overdetermined but consistent systems are accepted. | Inconsistent, underdetermined, nonlinear and parameterised systems are `unsupported`; a wrong tuple or ordering is `incorrect`. | Only linear equalities with a unique tuple are supported. |

`test_every_contract_has_at_least_ten_cases` enforces the count for the eleven
operation contracts required by the corpus. The one-variable `solve` bucket is a
companion group: it carries the required set, domain, `ne`, extraneous-root and
function-equation edge cases that the tuple-only linear-system contract cannot
express.

## Answer form is not assessed

For `evaluate`, `simplify`, `expand`, `factor` and `complete-square`, correctness
means algebraic equivalence on the problem domain. The corpus states this
explicitly:

- a factored answer passes `expand` (`expand/factored-answer-passes`);
- an unchanged but equivalent expression passes `complete-square`;
- an irreducible expression may pass `factor` unchanged.

LU is the exception: permutation and triangular structure are part of the
mathematical definition of a valid decomposition and are checked exactly.

## Domains, sets and refusals

- Intervals carry independent open/closed endpoints. Both endpoints absent means
  all reals.
- An empty `set` with no items and no intervals denotes the empty solution set.
- Integer and rational domains are enforced against declared symbol domains and
  the request domain; irrational candidates are rejected or left `unknown`.
- `ne` relations exclude exact points or sets. Original-AST guards are collected
  before SymPy cancels denominators, so a removed hole cannot be silently
  reintroduced.
- Extraneous roots from squaring or from rational equations are rejected when
  they violate the original relation or its source domain.
- `unknown` means the engine could not prove or disprove equality. It is never
  converted to `incorrect`.

## Defects repaired by this corpus

The corpus exposed three false verdicts, now fixed in the owned engine files:

1. **Periodic source-domain truncation.** `solve` with
   `log(sin(x)) = log(sin(x))` accepted only `(0, pi)` because SymPy's
   inequality helper evaluates one period. Non-`ne` conditions whose `sin`,
   `cos` or `tan` atom contains the variable now return `unknown` instead of
   silently shrinking the domain. See
   `solve/periodic-source-domain-refused`.
2. **Rational `ne` with an irrational exclusion.** Over the rationals,
   `x**2 != 2` is every rational, but the candidate all-reals interval was
   compared as `Interval(-oo, oo)` and left `unknown`. The `ne` solve path now
   short-circuits an empty in-domain exclusion set and candidate all-reals
   intervals normalise to `Reals`. See
   `solve/rational-domain-ne-irrational-exclusion`.
3. **Non-strict scalar domains.** `sqrt(x)*sqrt(y) -> sqrt(x*y)` was `unknown`
   because sign inference knew only strict `gt`/`lt` guards. A sign-category
   helper now classifies products, powers, sums, `abs` and `exp` under `ge`/`le`,
   and the `posify` proof is extended from the positive orthant to the
   nonnegative boundary by exact zero checks. See
   `expand/restricted-source-domain` and the equivalent scalar suite.

No corpus case needs `xfail`: every current expectation is either a decided
verdict or a documented refusal.
