"""Adversarial mutation tests for the deterministic maths engine.

The suite asks one question: can a small, meaning-preserving edit make the
engine reject a correct answer, or can a meaning-changing edit make it accept a
wrong one?  ``check_in_process`` is used for breadth; one preserving and one
breaking case per operation also go through the public isolated facade.

Soundness failures are hard failures: a meaning-changing edit that is not
``incorrect``, or a meaning-preserving edit that is not ``correct``, fails the
suite. ``unknown`` is treated as a coverage gap, never as a pass.
``docs/math-correctness-adversarial-findings.md`` records the history of the
defects that were found and fixed.
"""

from __future__ import annotations

import random
import time
from typing import Any

import pytest
from pydantic import ValidationError

from edcraft_validator.application.math_correctness import check_math_correctness
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
)
from edcraft_validator.domains.math.engine.dispatch import check_in_process
from edcraft_validator.domains.math.engine.validation import validate_request
from tests._math_mutations import (
    BREAKING,
    PRESERVING,
    Wire,
    add,
    applicable,
    interval,
    mul,
    num,
    power,
    sub,
    sym,
)

X = [{"name": "x"}]
XY = [{"name": "x"}, {"name": "y"}]


def _request(
    operation: str,
    *,
    symbols: list[dict[str, Any]],
    answer: Wire,
    **problem: Any,
) -> Wire:
    return {
        "problem": {"operation": operation, "symbols": symbols, **problem},
        "answer": answer,
    }


def _expression(value: Wire) -> Wire:
    return {"kind": "expression", "expression": value}


def _set(
    items: list[Wire] | None = None,
    intervals: list[Wire] | None = None,
) -> Wire:
    answer: Wire = {"kind": "set"}
    if items is not None:
        answer["items"] = items
    if intervals is not None:
        answer["intervals"] = intervals
    return answer


def _matrix(rows: list[list[Wire]]) -> Wire:
    return {"kind": "matrix", "matrix": rows}


def _tuple(items: list[Wire]) -> Wire:
    return {"kind": "tuple", "items": items}


def _lu(
    permutation: list[list[Wire]],
    lower: list[list[Wire]],
    upper: list[list[Wire]],
) -> Wire:
    return {
        "kind": "lu",
        "permutation": permutation,
        "lower": lower,
        "upper": upper,
    }


def _numbers(rows: list[list[object]]) -> list[list[Wire]]:
    return [
        [cell if isinstance(cell, dict) else num(cell) for cell in row] for row in rows
    ]


BASE_REQUESTS: dict[str, Wire] = {
    "evaluate.polynomial": _request(
        "evaluate",
        symbols=X,
        expression=add(power(sym("x"), 2), mul(2, sym("x")), mul(3, sym("x")), num(1)),
        answer=_expression(add(power(sym("x"), 2), mul(5, sym("x")), num(1))),
    ),
    "evaluate.distributed_product": _request(
        "evaluate",
        symbols=X,
        expression=mul(num(2), add(sym("x"), num(3))),
        answer=_expression(add(mul(2, sym("x")), num(6))),
    ),
    "simplify.rational": _request(
        "simplify",
        symbols=X,
        expression={
            "op": "div",
            "args": [sub(power(sym("x"), 2), num(1)), sub(sym("x"), num(1))],
        },
        answer=_expression(add(sym("x"), num(1))),
    ),
    "expand.square": _request(
        "expand",
        symbols=X,
        expression=power(add(sym("x"), num(1)), 2),
        answer=_expression(add(power(sym("x"), 2), mul(2, sym("x")), num(1))),
    ),
    "factor.quadratic": _request(
        "factor",
        symbols=X,
        expression=add(power(sym("x"), 2), mul(2, sym("x")), num(1)),
        answer=_expression(power(add(sym("x"), num(1)), 2)),
    ),
    "complete-square.quadratic": _request(
        "complete-square",
        symbols=X,
        expression=add(power(sym("x"), 2), mul(4, sym("x")), num(1)),
        answer=_expression(sub(power(add(sym("x"), num(2)), 2), num(3))),
    ),
    "differentiate.quartic": _request(
        "differentiate",
        symbols=X,
        expression=add(power(sym("x"), 4), {"op": "sin", "args": [sym("x")]}),
        answer=_expression(
            add(mul(4, power(sym("x"), 3)), {"op": "cos", "args": [sym("x")]})
        ),
        variable="x",
    ),
    "antiderivative.quartic": _request(
        "antiderivative",
        symbols=X,
        expression=add(mul(4, power(sym("x"), 3)), {"op": "cos", "args": [sym("x")]}),
        answer=_expression(add(power(sym("x"), 4), {"op": "sin", "args": [sym("x")]})),
        variable="x",
    ),
    "definite-integral.quadratic": _request(
        "definite-integral",
        symbols=X,
        expression=add(power(sym("x"), 2), num(1)),
        answer=_expression(num("4/3")),
        variable="x",
        lower=num(0),
        upper=num(1),
    ),
    "solve.quadratic": _request(
        "solve",
        symbols=X,
        relations=[{"kind": "eq", "lhs": power(sym("x"), 2), "rhs": num(4)}],
        solve_for=["x"],
        answer=_set(items=[num(-2), num(2)]),
    ),
    "solve.inequality-closed": _request(
        "solve",
        symbols=X,
        relations=[{"kind": "ge", "lhs": power(sym("x"), 2), "rhs": num(1)}],
        solve_for=["x"],
        answer=_set(
            intervals=[
                interval(None, num(-1), upper_open=False),
                interval(num(1), None, lower_open=False),
            ]
        ),
    ),
    "solve.inequality-open": _request(
        "solve",
        symbols=X,
        relations=[{"kind": "gt", "lhs": power(sym("x"), 2), "rhs": num(1)}],
        solve_for=["x"],
        answer=_set(intervals=[interval(None, num(-1)), interval(num(1), None)]),
    ),
    "solve.linear-system": _request(
        "solve",
        symbols=XY,
        relations=[
            {"kind": "eq", "lhs": add(mul(2, sym("x")), sym("y")), "rhs": num(5)},
            {"kind": "eq", "lhs": sub(sym("x"), sym("y")), "rhs": num(1)},
        ],
        solve_for=["x", "y"],
        answer=_tuple([num(2), num(1)]),
    ),
    "matrix-multiply.2x2": _request(
        "matrix-multiply",
        symbols=[],
        matrix=_numbers([[1, 2], [3, 4]]),
        right_matrix=_numbers([[0, 1], [1, 0]]),
        answer=_matrix(_numbers([[2, 1], [4, 3]])),
    ),
    "determinant.3x3": _request(
        "determinant",
        symbols=[],
        matrix=_numbers([[2, 1, 0], [1, 3, 1], [0, 1, 4]]),
        answer=_expression(num(18)),
    ),
    "inverse.3x3": _request(
        "inverse",
        symbols=[],
        matrix=_numbers([[2, 1, 0], [1, 2, 1], [0, 1, 2]]),
        answer=_matrix(
            _numbers(
                [
                    ["3/4", "-1/2", "1/4"],
                    ["-1/2", 1, "-1/2"],
                    ["1/4", "-1/2", "3/4"],
                ]
            )
        ),
    ),
    "lu.2x2": _request(
        "lu",
        symbols=[],
        matrix=_numbers([[2, 1], [4, 3]]),
        answer=_lu(
            _numbers([[1, 0], [0, 1]]),
            _numbers([[1, 0], [2, 1]]),
            _numbers([[2, 1], [0, 1]]),
        ),
    ),
}


def _cases(mutations: tuple[tuple[str, Any], ...]) -> list[tuple[str, str, Wire]]:
    cases: list[tuple[str, str, Wire]] = []
    for base_id, request in BASE_REQUESTS.items():
        for mutation_name, mutated in applicable(request, mutations):
            cases.append((base_id, mutation_name, mutated))
    return cases


PRESERVING_CASES = _cases(PRESERVING)
BREAKING_CASES = _cases(BREAKING)


def _run(request: Wire) -> CorrectnessResult:
    return check_in_process(CorrectnessRequest.model_validate(request))


def _case_id(base_id: str, mutation_name: str) -> str:
    return f"{base_id}.{mutation_name}"


def test_base_requests_are_accepted() -> None:
    """Every mutation is measured against a base the engine already accepts."""
    failures = []
    for base_id, request in BASE_REQUESTS.items():
        result = _run(request)
        if result.outcome != "correct":
            failures.append(f"{base_id}: {result.outcome} ({result.reason})")
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize(
    ("base_id", "mutation_name", "mutated"),
    PRESERVING_CASES,
    ids=[_case_id(base, mutation) for base, mutation, _ in PRESERVING_CASES],
)
def test_preserving_mutations_are_accepted(
    base_id: str, mutation_name: str, mutated: Wire
) -> None:
    """A meaning-preserving edit must stay ``correct``, not merely non-incorrect.

    Accepting ``unknown`` here would hide an over-refusal regression, so the
    outcome is asserted exactly. A genuinely undecidable case would have to be
    marked ``xfail`` individually with its reason.
    """
    result = _run(mutated)
    case = _case_id(base_id, mutation_name)
    assert result.outcome == "correct", (
        f"D-preserve.{case}: meaning-preserving edit is {result.outcome}, not "
        f"correct ({result.reason})"
    )


@pytest.mark.parametrize(
    ("base_id", "mutation_name", "mutated"),
    BREAKING_CASES,
    ids=[_case_id(base, mutation) for base, mutation, _ in BREAKING_CASES],
)
def test_breaking_mutations_are_rejected(
    base_id: str, mutation_name: str, mutated: Wire
) -> None:
    """A meaning-changing edit must be ``incorrect``, not merely non-correct.

    Accepting ``unknown`` here would hide an under-decision regression, so the
    outcome is asserted exactly. A genuinely undecidable case would have to be
    marked ``xfail`` individually with its reason.
    """
    result = _run(mutated)
    case = _case_id(base_id, mutation_name)
    assert result.outcome == "incorrect", (
        f"D-break.{case}: meaning-changing edit is {result.outcome}, not "
        f"incorrect ({result.reason})"
    )


def test_preserving_unknown_rate_stays_below_half() -> None:
    """Unknowns are a coverage gap, not a defect, but they must stay bounded.

    The outcomes are recomputed here rather than read from module globals so
    that ``pytest -k unknown_rate`` is meaningful on its own.
    """
    outcomes = [(case, _run(mutated)) for *case, mutated in PRESERVING_CASES]
    unknown = [
        f"{_case_id(base, mutation)}: {result.reason}"
        for (base, mutation), result in outcomes
        if result.outcome == "unknown"
    ]
    total = len(outcomes)
    rate = len(unknown) / total if total else 0.0
    print(f"\npreserving unknown: {len(unknown)}/{total} ({rate:.1%})")
    for case in unknown:
        print(f"  unknown {case}")
    assert rate < 0.5


def _sqrt(value: Wire) -> Wire:
    return {"op": "sqrt", "args": [value]}


_UNDEFINED_COMPLEX = power(_sqrt(num(-1)), 2)

UNDEFINED_CANDIDATE_CASES: dict[str, Wire] = {
    "determinant": _request(
        "determinant",
        symbols=[],
        matrix=_numbers([[-1, 0], [0, 1]]),
        answer=_expression(_UNDEFINED_COMPLEX),
    ),
    "matrix-multiply": _request(
        "matrix-multiply",
        symbols=[],
        matrix=_numbers([[1]]),
        right_matrix=_numbers([[-1]]),
        answer=_matrix([[_UNDEFINED_COMPLEX]]),
    ),
    "inverse": _request(
        "inverse",
        symbols=[],
        matrix=_numbers([[-1]]),
        answer=_matrix([[_UNDEFINED_COMPLEX]]),
    ),
    "lu": _request(
        "lu",
        symbols=[],
        matrix=_numbers([[-1]]),
        answer=_lu([[num(1)]], [[num(1)]], [[_UNDEFINED_COMPLEX]]),
    ),
    "solve.point": _request(
        "solve",
        symbols=X,
        relations=[{"kind": "eq", "lhs": sym("x"), "rhs": num(-1)}],
        solve_for=["x"],
        answer=_set(items=[_UNDEFINED_COMPLEX]),
    ),
    "solve.tuple": _request(
        "solve",
        symbols=XY,
        relations=[
            {"kind": "eq", "lhs": sym("x"), "rhs": num(-1)},
            {"kind": "eq", "lhs": sym("y"), "rhs": num(1)},
        ],
        solve_for=["x", "y"],
        answer=_tuple([_UNDEFINED_COMPLEX, num(1)]),
    ),
}


@pytest.mark.parametrize(
    "case", UNDEFINED_CANDIDATE_CASES, ids=list(UNDEFINED_CANDIDATE_CASES)
)
def test_undefined_complex_candidate_is_unsupported(case: str) -> None:
    """A finite non-real intermediate must be erased nowhere and refused.

    ``sqrt(-1)**2`` is ``-1`` only under complex arithmetic; no real value is
    assigned to ``sqrt(-1)``. The documented contract is an exact
    ``unsupported`` verdict before any cancellation can accept the answer.
    """
    result = _run(UNDEFINED_CANDIDATE_CASES[case])
    assert result.outcome == "unsupported", (
        "D-complex-undefined: candidate cancels an undefined non-real "
        f"subexpression and is {result.outcome} in {case} ({result.reason})"
    )


def _facade_cases() -> list[tuple[str, str, str, Wire]]:
    selected: list[tuple[str, str, str, Wire]] = []
    for base_id, request in BASE_REQUESTS.items():
        for kind, mutations in (("preserving", PRESERVING), ("breaking", BREAKING)):
            choices = applicable(request, mutations)
            assert choices, f"{base_id} has no {kind} mutation"
            mutation_name, mutated = choices[0]
            selected.append((base_id, kind, mutation_name, mutated))
    return selected


FACADE_CASES = _facade_cases()


@pytest.mark.parametrize(
    ("base_id", "kind", "mutation_name", "mutated"),
    FACADE_CASES,
    ids=[f"{base}.{kind}.{mutation}" for base, kind, mutation, _ in FACADE_CASES],
)
def test_isolated_facade_preserves_the_in_process_verdict(
    base_id: str, kind: str, mutation_name: str, mutated: Wire
) -> None:
    in_process = _run(mutated)
    facade = check_math_correctness(CorrectnessRequest.model_validate(mutated))
    expected = "correct" if kind == "preserving" else "incorrect"
    assert facade.outcome == in_process.outcome, (
        f"{base_id}.{kind}.{mutation_name}: in-process={in_process.outcome} "
        f"facade={facade.outcome}"
    )
    assert in_process.outcome == expected, (
        f"D-facade.{base_id}: {kind} case is {in_process.outcome}, not {expected}"
    )


# ---------------------------------------------------------------------------
# Validator fuzzing


def _leaf(rng: random.Random) -> Wire:
    return sym("x") if rng.random() < 0.75 else num(rng.choice([0, 1, -1, 2, 3]))


def _random_tree(rng: random.Random, budget: int, depth: int = 0) -> Wire:
    """Build a tree with exactly ``budget`` nodes and bounded recursion depth."""
    if budget <= 1 or depth >= 7:
        return _leaf(rng)
    if budget == 2:
        return {"op": "sin", "args": [_leaf(rng)]}
    kind = rng.choice(["add", "mul", "sub", "pow", "sin", "cos", "add", "mul"])
    if kind == "sin" or kind == "cos":
        return {"op": kind, "args": [_random_tree(rng, budget - 1, depth + 1)]}
    if kind == "pow":
        exponent = rng.choice([2, 3])
        return power(_random_tree(rng, budget - 2, depth + 1), exponent)
    left_budget = rng.randint(1, budget - 2)
    right_budget = budget - 1 - left_budget
    if kind == "sub":
        return sub(
            _random_tree(rng, left_budget, depth + 1),
            _random_tree(rng, right_budget, depth + 1),
        )
    return {
        "op": kind,
        "args": [
            _random_tree(rng, left_budget, depth + 1),
            _random_tree(rng, right_budget, depth + 1),
        ],
    }


def _wide_random_tree(rng: random.Random, budget: int) -> Wire:
    """Build a broad tree that really reaches the requested node count.

    The validator caps a single expression at 200 nodes, so a depth-capped
    binary tree cannot exercise the budget.  Wide ``add``/``mul`` nodes can,
    while still being cheap to construct and reject.
    """
    if budget <= 9:
        return _random_tree(rng, budget)
    arity = min(1000, max(2, budget // 2))
    remaining = budget - 1
    share, extra = divmod(remaining, arity)
    children = [
        _wide_random_tree(rng, share + (1 if index < extra else 0))
        for index in range(arity)
    ]
    return {"op": rng.choice(["add", "mul"]), "args": children}


def _fuzz_request(expression: Wire) -> Wire:
    return _request(
        "evaluate",
        symbols=X,
        expression=expression,
        answer=_expression(num(0)),
    )


def _iter_fuzz_sizes() -> tuple[int, ...]:
    return (512, 1500, 3000, 5000)


@pytest.mark.parametrize("node_budget", _iter_fuzz_sizes())
def test_large_random_trees_are_rejected_or_bounded(node_budget: int) -> None:
    """Validation must reject oversized trees before any expensive expansion."""
    rng = random.Random(20261113 + node_budget)
    expression = _wide_random_tree(rng, node_budget)
    request = CorrectnessRequest.model_validate(_fuzz_request(expression))

    started = time.perf_counter()
    try:
        validate_request(request)
    except (ValueError, ValidationError):
        rejected = True
    else:
        rejected = False
    validation_seconds = time.perf_counter() - started
    assert validation_seconds < 2.0

    if rejected:
        assert node_budget > 200
    else:
        # Only accepted trees may reach SymPy, and they must stay bounded.
        result = check_in_process(request)
        assert result.duration_ms < 2000.0, (
            f"accepted {node_budget}-node tree took {result.duration_ms:.0f} ms"
        )


def _safe_sum_tree(rng: random.Random, budget: int) -> Wire:
    """A random tree whose only growth is additive, safe if it is accepted."""
    if budget <= 1:
        return _leaf(rng)
    if budget == 2:
        return {"op": rng.choice(["sin", "cos"]), "args": [_leaf(rng)]}
    kind = rng.choice(["add", "sub", "sin", "cos"])
    if kind in {"sin", "cos"}:
        return {"op": kind, "args": [_safe_sum_tree(rng, budget - 1)]}
    left_budget = rng.randint(1, budget - 2)
    right_budget = budget - 1 - left_budget
    if kind == "add":
        return add(
            _safe_sum_tree(rng, left_budget),
            _safe_sum_tree(rng, right_budget),
        )
    return sub(
        _safe_sum_tree(rng, left_budget),
        _safe_sum_tree(rng, right_budget),
    )


def test_accepted_random_tree_finishes_within_two_seconds() -> None:
    rng = random.Random(20261113)
    request = CorrectnessRequest.model_validate(_fuzz_request(_safe_sum_tree(rng, 20)))
    validate_request(request)
    result = check_in_process(request)
    assert result.duration_ms < 2000.0
