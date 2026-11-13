"""Reusable, pure mutations over the maths-correctness wire format.

Every mutation takes a plain ``CorrectnessRequest`` dict and returns either a
new dict (leaving the input untouched) or ``None`` when the request does not
supply the structure the mutation needs.  The two families are:

* ``PRESERVING`` mutations change syntax while keeping the mathematical
  meaning, so the engine must not answer ``incorrect``.
* ``BREAKING`` mutations change the answer or the problem meaningfully, so the
  engine must not answer ``correct``.

The helpers deliberately know nothing about the engine handlers; they only
manipulate the public request shape from ``engine/contracts.py``.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Callable, Iterable
from fractions import Fraction
from typing import Any

Wire = dict[str, Any]
Mutation = tuple[str, Callable[[Wire], Wire | None]]

_TERM = tuple[tuple[str, int], ...]
_Polynomial = dict[_TERM, Fraction]


# ---------------------------------------------------------------------------
# Wire constructors


def num(value: object) -> Wire:
    return {"num": str(value)}


def sym(name: str) -> Wire:
    return {"sym": name}


def _wire(value: object) -> Wire:
    if isinstance(value, dict):
        return value
    if isinstance(value, (int, Fraction)):
        return {"num": str(value)}
    raise TypeError(f"cannot convert {value!r} to an expression node")


def op(name: str, *args: Wire) -> Wire:
    return {"op": name, "args": [_wire(arg) for arg in args]}


def add(*args: Wire) -> Wire:
    return op("add", *args)


def mul(*args: Wire) -> Wire:
    return op("mul", *args)


def sub(left: Wire, right: Wire) -> Wire:
    return op("sub", left, right)


def power(base: Wire, exponent: object) -> Wire:
    return op("pow", base, num(exponent))


def negate(value: Wire) -> Wire:
    return mul(num(-1), value)


def interval(
    lower: Wire | None,
    upper: Wire | None,
    *,
    lower_open: bool = True,
    upper_open: bool = True,
) -> Wire:
    return {
        "lower": lower,
        "upper": upper,
        "lower_open": lower_open,
        "upper_open": upper_open,
    }


# ---------------------------------------------------------------------------
# Structural helpers


def _is_expr(value: object) -> bool:
    return isinstance(value, dict) and any(
        key in value for key in ("num", "sym", "param", "op")
    )


def _answer_slots(request: Wire) -> list[tuple[Any, ...]]:
    """Paths to every expression held by the answer."""
    paths: list[tuple[Any, ...]] = []
    answer = request["answer"]
    if _is_expr(answer.get("expression")):
        paths.append(("answer", "expression"))
    for index, item in enumerate(answer.get("items") or []):
        if _is_expr(item):
            paths.append(("answer", "items", index))
    for index, bounds in enumerate(answer.get("intervals") or []):
        for side in ("lower", "upper"):
            if _is_expr(bounds.get(side)):
                paths.append(("answer", "intervals", index, side))
    for field in ("matrix", "permutation", "lower", "upper"):
        rows = answer.get(field)
        if not rows:
            continue
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                if _is_expr(cell):
                    paths.append(("answer", field, row_index, column_index))
    return paths


def _problem_slots(request: Wire) -> list[tuple[Any, ...]]:
    """Paths to every expression held by the problem."""
    problem = request["problem"]
    paths: list[tuple[Any, ...]] = []
    for field in ("expression", "lower", "upper"):
        if _is_expr(problem.get(field)):
            paths.append(("problem", field))
    for index, relation in enumerate(problem.get("relations") or []):
        for side in ("lhs", "rhs"):
            if _is_expr(relation.get(side)):
                paths.append(("problem", "relations", index, side))
    for field in ("matrix", "right_matrix"):
        rows = problem.get(field)
        if not rows:
            continue
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                if _is_expr(cell):
                    paths.append(("problem", field, row_index, column_index))
    return paths


def _all_slots(request: Wire) -> list[tuple[Any, ...]]:
    return _answer_slots(request) + _problem_slots(request)


def _get(request: Wire, path: tuple[Any, ...]) -> Wire:
    node: Any = request
    for key in path:
        node = node[key]
    return node


def _set(request: Wire, path: tuple[Any, ...], value: Wire) -> None:
    node: Any = request
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _map_tree(expr: Wire, transform: Callable[[Wire], Wire]) -> Wire:
    """Apply ``transform`` bottom-up, rebuilding parents (pure)."""
    rebuilt = {key: value for key, value in expr.items() if key != "args"}
    if "args" in expr:
        rebuilt["args"] = [_map_tree(child, transform) for child in expr["args"]]
    return transform(rebuilt)


def _transform_all(
    request: Wire,
    transform: Callable[[Wire], Wire],
    *,
    answer_only: bool = False,
) -> Wire:
    mutated = copy.deepcopy(request)
    paths = _answer_slots(mutated) if answer_only else _all_slots(mutated)
    for path in paths:
        _set(mutated, path, _map_tree(_get(mutated, path), transform))
    return mutated


def _has_node(expr: Wire, predicate: Callable[[Wire], bool]) -> bool:
    if predicate(expr):
        return True
    return any(_has_node(child, predicate) for child in expr.get("args", []))


def _exponent_is(expr: Wire, value: int) -> bool:
    if expr.get("op") != "pow" or len(expr.get("args", [])) != 2:
        return False
    exponent = expr["args"][1]
    if exponent.get("num") is None:
        return False
    try:
        return Fraction(exponent["num"]) == value
    except (ValueError, ZeroDivisionError):
        return False


def _first_path(
    request: Wire, predicate: Callable[[Wire], bool]
) -> tuple[Any, ...] | None:
    for path in _all_slots(request):
        if _has_node(_get(request, path), predicate):
            return path
    return None


# ---------------------------------------------------------------------------
# Small exact polynomial engine (expand-then-collect)


def _poly_constant(value: Fraction) -> _Polynomial:
    return {} if value == 0 else {(): value}


def _poly_add(left: _Polynomial, right: _Polynomial) -> _Polynomial:
    result = dict(left)
    for term, coefficient in right.items():
        result[term] = result.get(term, Fraction(0)) + coefficient
        if result[term] == 0:
            del result[term]
    return result


def _poly_mul(left: _Polynomial, right: _Polynomial) -> _Polynomial | None:
    if len(left) * len(right) > 512:
        return None
    result: _Polynomial = {}
    for left_term, left_coefficient in left.items():
        for right_term, right_coefficient in right.items():
            merged = dict(left_term)
            for name, exponent in right_term:
                merged[name] = merged.get(name, 0) + exponent
            term = tuple(sorted(merged.items()))
            result[term] = (
                result.get(term, Fraction(0)) + left_coefficient * right_coefficient
            )
    return {term: value for term, value in result.items() if value != 0}


def _poly_scale(value: _Polynomial, factor: Fraction) -> _Polynomial:
    return {
        term: coefficient * factor
        for term, coefficient in value.items()
        if coefficient * factor != 0
    }


def _poly_of(expr: Wire) -> _Polynomial | None:
    if expr.get("num") is not None:
        try:
            return _poly_constant(Fraction(expr["num"]))
        except (ValueError, ZeroDivisionError):
            return None
    if expr.get("sym") is not None:
        return {((expr["sym"], 1),): Fraction(1)}
    operator = expr.get("op")
    args = expr.get("args") or []
    if operator is None:
        return None
    if operator == "add":
        total: _Polynomial = {}
        for child in args:
            part = _poly_of(child)
            if part is None:
                return None
            total = _poly_add(total, part)
        return total
    if operator == "sub" and len(args) == 2:
        left, right = _poly_of(args[0]), _poly_of(args[1])
        if left is None or right is None:
            return None
        return _poly_add(left, _poly_scale(right, Fraction(-1)))
    if operator == "mul":
        total = _poly_constant(Fraction(1))
        for child in args:
            part = _poly_of(child)
            if part is None:
                return None
            product = _poly_mul(total, part)
            if product is None:
                return None
            total = product
        return total
    if operator == "pow" and len(args) == 2 and args[1].get("num") is not None:
        try:
            exponent = Fraction(args[1]["num"])
        except (ValueError, ZeroDivisionError):
            return None
        if exponent.denominator != 1 or not 0 <= exponent <= 12:
            return None
        base = _poly_of(args[0])
        if base is None:
            return None
        result = _poly_constant(Fraction(1))
        for _ in range(int(exponent)):
            product = _poly_mul(result, base)
            if product is None:
                return None
            result = product
        return result
    if operator == "div" and len(args) == 2:
        left, right = _poly_of(args[0]), _poly_of(args[1])
        if left is None or right is None or list(right) != [()] or right[()] == 0:
            return None
        return _poly_scale(left, Fraction(1) / right[()])
    return None


def _poly_expr(polynomial: _Polynomial) -> Wire:
    if not polynomial:
        return num(0)
    terms: list[Wire] = []
    for term in sorted(polynomial):
        coefficient = polynomial[term]
        factors: list[Wire] = []
        if coefficient != 1 or not term:
            factors.append(num(coefficient))
        for name, exponent in term:
            factors.append(sym(name) if exponent == 1 else power(sym(name), exponent))
        terms.append(factors[0] if len(factors) == 1 else mul(*factors))
    return terms[0] if len(terms) == 1 else add(*terms)


def _needs_expansion(expr: Wire) -> bool:
    if expr.get("op") == "mul":
        if any(child.get("op") == "add" for child in expr["args"]):
            return True
    if expr.get("op") == "pow" and len(expr.get("args", [])) == 2:
        base = expr["args"][0]
        if base.get("op") == "add" and any(
            _exponent_is(expr, value) for value in range(2, 13)
        ):
            return True
    return any(_needs_expansion(child) for child in expr.get("args", []))


# ---------------------------------------------------------------------------
# Semantics-preserving mutations


def reorder_add_arguments(request: Wire) -> Wire:
    def swap(expr: Wire) -> Wire:
        if expr.get("op") == "add" and len(expr["args"]) >= 2:
            return {**expr, "args": list(reversed(expr["args"]))}
        return expr

    return _transform_all(request, swap)


def reorder_mul_arguments(request: Wire) -> Wire:
    def swap(expr: Wire) -> Wire:
        if expr.get("op") == "mul" and len(expr["args"]) >= 2:
            return {**expr, "args": list(reversed(expr["args"]))}
        return expr

    return _transform_all(request, swap)


def add_zero(request: Wire) -> Wire:
    path = _first_path(request, lambda expr: True)
    if path is None:
        return None
    mutated = copy.deepcopy(request)
    _set(mutated, path, add(_get(mutated, path), num(0)))
    return mutated


def multiply_by_one(request: Wire) -> Wire:
    path = _first_path(request, lambda expr: True)
    if path is None:
        return None
    mutated = copy.deepcopy(request)
    _set(mutated, path, mul(_get(mutated, path), num(1)))
    return mutated


def subtract_as_add_negative_product(request: Wire) -> Wire:
    def rewrite(expr: Wire) -> Wire:
        if expr.get("op") == "sub" and len(expr["args"]) == 2:
            return add(expr["args"][0], mul(num(-1), expr["args"][1]))
        return expr

    if _first_path(request, lambda expr: expr.get("op") == "sub") is None:
        return None
    return _transform_all(request, rewrite)


def square_as_product(request: Wire) -> Wire:
    def rewrite(expr: Wire) -> Wire:
        if _exponent_is(expr, 2):
            base = expr["args"][0]
            return mul(base, copy.deepcopy(base))
        return expr

    if _first_path(request, lambda expr: _exponent_is(expr, 2)) is None:
        return None
    return _transform_all(request, rewrite)


def distribute_then_collect(request: Wire) -> Wire:
    """Expand products/powers and re-collect like terms, purely symbolically."""
    changed = False
    mutated = copy.deepcopy(request)
    for path in _all_slots(mutated):
        expr = _get(mutated, path)
        if not _needs_expansion(expr):
            continue
        polynomial = _poly_of(expr)
        if polynomial is None:
            continue
        _set(mutated, path, _poly_expr(polynomial))
        changed = True
    return mutated if changed else None


def alternate_interval_representation(request: Wire) -> Wire:
    answer = request["answer"]
    if answer.get("kind") != "set" or not answer.get("intervals"):
        return None
    mutated = copy.deepcopy(request)
    answer = mutated["answer"]
    items = answer.setdefault("items", [])

    for bounds in answer["intervals"]:
        for side, flag in (("lower", "lower_open"), ("upper", "upper_open")):
            endpoint = bounds.get(side)
            if endpoint is None or bounds.get(flag):
                continue
            items.append(copy.deepcopy(endpoint))
            bounds[flag] = True
            return mutated

    for index, bounds in enumerate(answer["intervals"]):
        lower, upper = bounds.get("lower"), bounds.get("upper")
        lower_open, upper_open = bounds.get("lower_open"), bounds.get("upper_open")
        if lower is None or upper is None:
            continue
        left, right = _fraction(lower), _fraction(upper)
        if left is None or right is None or left >= right:
            continue
        middle = (left + right) / 2
        answer["intervals"][index : index + 1] = [
            interval(lower, num(middle), lower_open=lower_open, upper_open=True),
            interval(num(middle), upper, lower_open=True, upper_open=upper_open),
        ]
        return mutated
    return None


def alternate_lu_permutation(request: Wire) -> Wire | None:
    if request["problem"].get("operation") != "lu":
        return None
    matrix = _numeric_matrix(request["problem"].get("matrix"))
    if matrix is None or len(matrix) != len(matrix[0]) or len(matrix) > 4:
        return None
    answer = request["answer"]
    if answer.get("kind") != "lu":
        return None
    current = _permutation_indices(answer.get("permutation"))
    size = len(matrix)
    for permutation in itertools.permutations(range(size)):
        if permutation == tuple(range(size)) or permutation == current:
            continue
        factorisation = _lu_for_permutation(matrix, permutation)
        if factorisation is None:
            continue
        lower, upper = factorisation
        mutated = copy.deepcopy(request)
        mutated["answer"]["permutation"] = _identity_matrix(size, permutation)
        mutated["answer"]["lower"] = _matrix_wire(lower)
        mutated["answer"]["upper"] = _matrix_wire(upper)
        return mutated
    return None


def antiderivative_plus_constant(request: Wire) -> Wire | None:
    if request["problem"].get("operation") != "antiderivative":
        return None
    answer = request["answer"]
    if answer.get("kind") != "expression" or not _is_expr(answer.get("expression")):
        return None
    mutated = copy.deepcopy(request)
    mutated["answer"]["expression"] = add(mutated["answer"]["expression"], num(7))
    return mutated


# ---------------------------------------------------------------------------
# Semantics-breaking mutations


def perturb_answer_coefficient(request: Wire) -> Wire | None:
    for path in _answer_slots(request):
        if "intervals" in path:
            continue
        found = _first_number_path(_get(request, path))
        if found is None:
            continue
        mutated = copy.deepcopy(request)
        target = _get(mutated, path)
        leaf = _get(target, found)
        _set(mutated, (*path, *found), str(Fraction(leaf) + 1))
        return mutated
    return None


def flip_answer_sign(request: Wire) -> Wire | None:
    answer = request["answer"]
    mutated = copy.deepcopy(request)
    if (
        answer.get("kind") == "expression"
        and _is_expr(answer.get("expression"))
        and not _is_zero_number(answer["expression"])
    ):
        mutated["answer"]["expression"] = negate(answer["expression"])
        return mutated
    for path in _answer_slots(request):
        if "intervals" in path:
            continue
        if _is_zero_number(_get(request, path)):
            continue
        if path[1] in {"items", "matrix", "permutation", "lower", "upper"}:
            _set(mutated, path, negate(_get(mutated, path)))
            return mutated
    return None


def add_extraneous_solution(request: Wire) -> Wire | None:
    answer = request["answer"]
    if answer.get("kind") != "set":
        return None
    candidate = next(
        (
            value
            for value in (0, 1, -1, 2, -2, 1000, -1000, 3, -3)
            if not _set_contains(answer, Fraction(value))
        ),
        None,
    )
    if candidate is None:
        return None
    mutated = copy.deepcopy(request)
    mutated["answer"].setdefault("items", []).append(num(candidate))
    return mutated


def drop_solution_item(request: Wire) -> Wire | None:
    answer = request["answer"]
    mutated = copy.deepcopy(request)
    answer = mutated["answer"]
    if answer.get("kind") == "set":
        items = answer.get("items") or []
        if len(items) > 1:
            answer["items"] = items[:-1]
            return mutated
        intervals = answer.get("intervals") or []
        if len(intervals) > 1:
            answer["intervals"] = intervals[:-1]
            return mutated
        return None
    if answer.get("kind") == "tuple" and len(answer.get("items") or []) > 1:
        answer["items"] = answer["items"][:-1]
        return mutated
    return None


def flip_inequality_direction(request: Wire) -> Wire | None:
    if request["problem"].get("operation") != "solve":
        return None
    opposite = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le"}
    relations = request["problem"].get("relations") or []
    if not any(relation.get("kind") in opposite for relation in relations):
        return None
    mutated = copy.deepcopy(request)
    for relation in mutated["problem"]["relations"]:
        if relation.get("kind") in opposite:
            relation["kind"] = opposite[relation["kind"]]
            return mutated
    return None


def change_interval_endpoint_by_one(request: Wire) -> Wire | None:
    answer = request["answer"]
    if answer.get("kind") != "set":
        return None
    mutated = copy.deepcopy(request)
    for bounds in mutated["answer"].get("intervals") or []:
        for side in ("upper", "lower"):
            endpoint = bounds.get(side)
            if endpoint is None:
                continue
            bounds[side] = add(endpoint, num(1))
            return mutated
    return None


def close_open_endpoint(request: Wire) -> Wire | None:
    answer = request["answer"]
    if answer.get("kind") != "set":
        return None
    mutated = copy.deepcopy(request)
    for bounds in mutated["answer"].get("intervals") or []:
        for side, flag in (("lower", "lower_open"), ("upper", "upper_open")):
            if bounds.get(side) is not None and bounds.get(flag):
                bounds[flag] = False
                return mutated
    return None


def swap_matrix_entries(request: Wire) -> Wire | None:
    for field in ("matrix", "permutation", "lower", "upper"):
        rows = request["answer"].get(field)
        if not rows or len(rows) < 2 or len(rows[0]) < 2:
            continue
        if rows[0][0] == rows[0][1]:
            continue
        mutated = copy.deepcopy(request)
        cells = mutated["answer"][field]
        cells[0][0], cells[0][1] = cells[0][1], cells[0][0]
        return mutated
    return None


def scale_lower_row(request: Wire) -> Wire | None:
    answer = request["answer"]
    if answer.get("kind") != "lu" or not answer.get("lower"):
        return None
    lower = answer["lower"]
    if len(lower) < 2:
        return None
    mutated = copy.deepcopy(request)
    row = mutated["answer"]["lower"][-1]
    mutated["answer"]["lower"][-1] = [mul(num(2), cell) for cell in row]
    return mutated


def use_non_permutation_matrix(request: Wire) -> Wire | None:
    answer = request["answer"]
    if answer.get("kind") != "lu" or not answer.get("permutation"):
        return None
    size = len(answer["permutation"])
    mutated = copy.deepcopy(request)
    mutated["answer"]["permutation"] = [
        [num(1) for _ in range(size)] for _ in range(size)
    ]
    return mutated


def change_derivative_order(request: Wire) -> Wire | None:
    problem = request["problem"]
    if problem.get("operation") != "differentiate":
        return None
    order = problem.get("order", 1)
    if order >= 8:
        return None
    mutated = copy.deepcopy(request)
    mutated["problem"]["order"] = order + 1
    return mutated


def change_definite_integral_bound(request: Wire) -> Wire | None:
    problem = request["problem"]
    if problem.get("operation") != "definite-integral":
        return None
    upper = problem.get("upper")
    if not _is_expr(upper):
        return None
    mutated = copy.deepcopy(request)
    mutated["problem"]["upper"] = add(upper, num(1))
    return mutated


# ---------------------------------------------------------------------------
# Registries


PRESERVING: tuple[Mutation, ...] = (
    ("reorder_add_arguments", reorder_add_arguments),
    ("reorder_mul_arguments", reorder_mul_arguments),
    ("add_zero", add_zero),
    ("multiply_by_one", multiply_by_one),
    ("subtract_as_add_negative_product", subtract_as_add_negative_product),
    ("square_as_product", square_as_product),
    ("distribute_then_collect", distribute_then_collect),
    ("alternate_interval_representation", alternate_interval_representation),
    ("alternate_lu_permutation", alternate_lu_permutation),
    ("antiderivative_plus_constant", antiderivative_plus_constant),
)

BREAKING: tuple[Mutation, ...] = (
    ("perturb_answer_coefficient", perturb_answer_coefficient),
    ("flip_answer_sign", flip_answer_sign),
    ("drop_solution_item", drop_solution_item),
    ("add_extraneous_solution", add_extraneous_solution),
    ("flip_inequality_direction", flip_inequality_direction),
    ("change_interval_endpoint_by_one", change_interval_endpoint_by_one),
    ("close_open_endpoint", close_open_endpoint),
    ("swap_matrix_entries", swap_matrix_entries),
    ("scale_lower_row", scale_lower_row),
    ("use_non_permutation_matrix", use_non_permutation_matrix),
    ("change_derivative_order", change_derivative_order),
    ("change_definite_integral_bound", change_definite_integral_bound),
)


# ---------------------------------------------------------------------------
# Internal matrix helpers


def _fraction(value: Wire) -> Fraction | None:
    if value.get("num") is None:
        return None
    try:
        return Fraction(value["num"])
    except (ValueError, ZeroDivisionError):
        return None


def _numeric_matrix(matrix: object) -> list[list[Fraction]] | None:
    if not isinstance(matrix, list) or not matrix:
        return None
    result: list[list[Fraction]] = []
    for row in matrix:
        if not isinstance(row, list) or not row:
            return None
        converted: list[Fraction] = []
        for cell in row:
            value = _fraction(cell) if isinstance(cell, dict) else None
            if value is None:
                return None
            converted.append(value)
        result.append(converted)
    if len({len(row) for row in result}) != 1:
        return None
    return result


def _lu_for_permutation(
    matrix: list[list[Fraction]], permutation: tuple[int, ...]
) -> tuple[list[list[Fraction]], list[list[Fraction]]] | None:
    size = len(matrix)
    working = [list(matrix[row]) for row in permutation]
    lower = [
        [Fraction(1 if row == column else 0) for column in range(size)]
        for row in range(size)
    ]
    for pivot in range(size):
        value = working[pivot][pivot]
        if value == 0:
            return None
        for row in range(pivot + 1, size):
            factor = working[row][pivot] / value
            if factor == 0:
                continue
            lower[row][pivot] = factor
            for column in range(pivot, size):
                working[row][column] -= factor * working[pivot][column]
    upper = [[working[row][column] for column in range(size)] for row in range(size)]
    for row in range(size):
        for column in range(row):
            upper[row][column] = Fraction(0)
    return lower, upper


def _permutation_indices(matrix: object) -> tuple[int, ...] | None:
    if not isinstance(matrix, list) or not matrix:
        return None
    indices: list[int] = []
    for row in matrix:
        ones = [
            index
            for index, cell in enumerate(row)
            if isinstance(cell, dict) and _fraction(cell) == 1
        ]
        if len(ones) != 1:
            return None
        indices.append(ones[0])
    return tuple(indices)


def _matrix_wire(matrix: list[list[Fraction]]) -> list[list[Wire]]:
    return [[num(value) for value in row] for row in matrix]


def _identity_matrix(size: int, permutation: tuple[int, ...]) -> list[list[Wire]]:
    return [
        [num(1 if permutation[row] == column else 0) for column in range(size)]
        for row in range(size)
    ]


def _is_zero_number(expr: Wire) -> bool:
    if expr.get("num") is None:
        return False
    try:
        return Fraction(expr["num"]) == 0
    except (ValueError, ZeroDivisionError):
        return False


def _set_contains(answer: Wire, value: Fraction) -> bool:
    for item in answer.get("items") or []:
        if _fraction(item) == value:
            return True
    for bounds in answer.get("intervals") or []:
        lower = _fraction(bounds["lower"]) if bounds.get("lower") else None
        upper = _fraction(bounds["upper"]) if bounds.get("upper") else None
        if lower is not None and (
            value < lower or (value == lower and bounds.get("lower_open"))
        ):
            continue
        if upper is not None and (
            value > upper or (value == upper and bounds.get("upper_open"))
        ):
            continue
        return True
    return False


def _first_number_path(expr: Wire) -> tuple[Any, ...] | None:
    if expr.get("num") is not None:
        return ("num",)
    for index, child in enumerate(expr.get("args", [])):
        found = _first_number_path(child)
        if found is not None:
            return ("args", index, *found)
    return None


def applicable(request: Wire, mutations: Iterable[Mutation]) -> list[tuple[str, Wire]]:
    """Return ``(name, mutated_request)`` for every mutation that applies."""
    results: list[tuple[str, Wire]] = []
    for name, mutation in mutations:
        mutated = mutation(copy.deepcopy(request))
        if mutated is not None:
            results.append((name, mutated))
    return results
