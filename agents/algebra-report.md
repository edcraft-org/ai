# Algebra kernel review and completion

Ownership: `src/edcraft_validator/application/check_pilot/algebra_checks.py`
and `tests/test_check_pilot_algebra_checks.py` only.

Branch: `codex/math-check-expansion` (no push, merge or deploy).
Kernel commit: `00ec918` (`fix: close algebra form and answer-budget gaps`).
Reviewed baseline commits: `5761416`, `bffe754`, `13d2ae3`.

## What was wrong

The committed kernel passed its 15 original tests but had real false
positives and a closure failure at the advertised limits:

1. **Completed-square inner was only coefficient-checked.** A candidate such
   as `((x^2 + x + 2) - x^2)^2 - 3` was accepted for `(x+2)^2 - 3`, even
   though the inner expression was not an explicit monic linear form.
2. **The oracle could reject its own answer at legal limits.** For
   `x^2 + 1000x + 1000` (all expanded coefficients within the advertised
   bound), the completed-square constant is `-249000`. `check_answer` and
   `render_answer` used an implicit `100000` literal budget, so the oracle
   answer was rejected or rendering raised.
3. **Factor form accepted hidden-cancellation factors.** Irreducibility was
   decided from expanded coefficients only, so a factor such as
   `(x^2 + x) - x^2 - 1` was accepted as the explicit linear factor `x - 1`.
4. **Factor scalar handling was inconsistent.** Nested non-unit scalar
   products were accepted while the same scalars at one level were rejected.
   Valid alternative scalings should be accepted; only an explicit unit
   product is an identity evasion.
5. **Expanded form accepted `x^0` and `x^1` as monomials**, which are
   equivalent to constants/linear terms but are not collected expansions.
   The square exponent was compared to the literal string `"2"`, so an exact
   exponent written as `2/1` was rejected inconsistently.

## What changed

- Added explicit constants for every advertised bound: problem degree,
  problem numeric leaves, expanded coefficients, system entries, answer
  literals, rational text length, tree nodes and tree depth.
- Enforced **integer expanded coefficients** for the three polynomial
  contracts. This is now part of the documented scope and keeps every derived
  oracle value inside the explicit answer budget. Rational literals that
  expand to integer coefficients are still accepted.
- Replaced coefficient-only form checks with structural AST checks:
  - expansion: collected distinct monomials, explicit `x`/`x^k` (`k >= 2`),
    at most one numeric coefficient per term, no zero terms;
  - factorisation: flattened product, explicit expanded irreducible linear or
    quadratic factors, square powers of irreducible bases, and a non-trivial
    total scalar product; other non-unit scalar scalings are accepted;
  - completed square: square term first, numeric scalar `a != 0`, numeric
    constant `k`, and an explicit monic inner `x`, `x + h` or `x - h`.
- `check_answer` and `render_answer` now use the explicit answer literal
  budget, so oracle answers at the coefficient extremes are accepted and
  renderable.
- Canonicalised oracle output for negative roots/offsets (`x + 10` instead of
  `x - -10`) and omitted a zero additive constant from completed-square
  answers.
- Preserved the 128-bit intermediate `Fraction` budget, safe Expr compilation,
  no `eval`/`sympify`, SymPy only in the execution checker, and the existing
  public function/model/answer shapes.

## Tests and evidence

Focused command:

```text
.venv/bin/python -m pytest tests/test_check_pilot_algebra_checks.py -q
32 passed
```

Before the implementation the new tests were RED: **7 failed, 25 passed**.
After the fixes: **32 passed**. The suite now covers:

- hidden nonlinear cancellations in completed-square inners and factors;
- the `-249000` completed-square answer-budget closure case;
- alternative factor scalings/signs, repeated roots, irreducibles,
  identity-factor evasions and nested scalar products;
- exact rational linear systems, decimals/fractions, booleans/floats,
  singular and out-of-scope systems, wrong/missing/extra components;
- malformed, oversized and non-canonical candidate trees/literals;
- exact structural oracle snapshots for all four contracts;
- oracle independence by monkeypatching `sympy.solve/factor/diff/integrate`;
- distinct, genuinely wrong distractors for all boundary problems;
- Hypothesis round-trips for every strategy problem.

Additional independent checks run locally:

- exhaustive 726 small non-monic quadratics for factor and complete-square
  (`a in [-3,3]` excluding zero, `b,c in [-5,5]`): every oracle answer
  accepted, every distractor rejected, every answer rendered;
- exhaustive 110 linear factor problems (`ax+b`, `a != 0`);
- 400 randomised factor/square/expand/system problems at and around the
  coefficient limits: oracle accepted, distractors rejected (only a degenerate
  zero-polynomial generator case was invalid by construction);
- `kernel_registry` smoke test: all four algebra contracts load through the
  shared registry, accept their oracle and return six distinct distractors.

Lint/format/types:

```text
.venv/bin/ruff check .../algebra_checks.py tests/test_check_pilot_algebra_checks.py
All checks passed!
.venv/bin/ruff format --check .../algebra_checks.py tests/test_check_pilot_algebra_checks.py
2 files already formatted
.venv/bin/mypy .../algebra_checks.py
Success: no issues found in 1 source file
```

## Scope limitations (explicit)

- Polynomial algebra contracts accept integer expanded coefficients with
  absolute value at most 1000 and small exact literals (absolute value at most
  20). Rational literals are allowed only when the expansion is integral.
- Expansion degree is 1..5; factorisation degree is 1..2; completing the
  square is exactly degree 2.
- Factorisation is over the rationals only. Irreducible quadratics are
  accepted as their own fully factored answer.
- Completed-square answers require a single numeric scalar `a != 0`, an
  explicit monic inner `x +/- h`, and the square term before the numeric
  constant. A scalar product such as `2*3*(x-h)^2+k` is outside the form.
- Linear systems are exactly 2x2, strictly integer, entries in `[-20,20]`, and
  nonsingular. Rational solutions are returned exactly.
- Answer literals are bounded at `10_000_000`; expression trees at 80 nodes
  and depth 12. All bounds are checked before SymPy sees the candidate.
- These tests do not certify worked explanations, only final answers.
- No live SocLaas authoring was run here. Root/integration owns the live
  authoring harness; this module is ready for it.

## Integration notes

- The committed algebra problem kinds are `polynomial-expand`,
  `polynomial-factor`, `polynomial-complete-square`, and
  `linear-system-unique`. They intentionally keep the already-committed algebra
  API (`kind`/`expression`, `matrix`/`rhs`, answer shapes
  `{"expression": ...}` / `{"values": [...]}`) to avoid conflicts.
- Concrete problems, oracle answers, accepted alternatives and rejected
  adversarial candidates are in `agents/algebra-examples.json`.
- The shared integration layer should build its closed problem union from
  `PROBLEM_TYPES` and dispatch via the `CONTRACT_SPECS` kind, then adapt its
  family examples to these committed schemas.
