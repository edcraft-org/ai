"""Bound closed requests before any potentially expensive symbolic computation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    EngineUnknown,
    EngineUnsupported,
)
from edcraft_validator.domains.math.ir.schema import Expr

MAX_TOTAL_NODES = 1000
MAX_DEPTH = 24
MAX_MATRIX_DIMENSION = 8
MAX_LITERAL_BITS = 512
MAX_OUTPUT_TERMS = 20_000
_TERM_OVERFLOW = MAX_OUTPUT_TERMS + 1
_LITERAL = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?(?:/[+-]?\d+)?$"
)
_ARITY = {
    "add": (1, 1000),
    "mul": (1, 1000),
    "sub": (2, 2),
    "div": (2, 2),
    "pow": (2, 2),
    "sqrt": (1, 1),
    "abs": (1, 1),
    "exp": (1, 1),
    "sin": (1, 1),
    "cos": (1, 1),
    "tan": (1, 1),
    "asin": (1, 1),
    "acos": (1, 1),
    "atan": (1, 1),
    "log": (1, 2),
}


def bounded_number(text: str) -> Fraction:
    if len(text) > 128:
        raise EngineUnsupported("numeric literal exceeds length budget")
    matched = _LITERAL.fullmatch(text.strip())
    if matched is None:
        raise EngineUnsupported("numeric literals must be finite exact numbers")
    if matched[1] is not None and abs(int(matched[1])) > 128:
        raise EngineUnsupported("numeric exponent exceeds literal budget")
    try:
        number = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise EngineUnsupported("invalid exact numeric literal") from exc
    if (
        max(number.numerator.bit_length(), number.denominator.bit_length())
        > MAX_LITERAL_BITS
    ):
        raise EngineUnsupported("numeric literal exceeds bit budget")
    return number


def _clamp_terms(value: int) -> int:
    return _TERM_OVERFLOW if value > MAX_OUTPUT_TERMS else value


def _literal_integer(expr: Expr) -> int | None:
    if expr.num is None:
        return None
    try:
        number = bounded_number(expr.num)
    except EngineUnsupported:
        return None
    if number.denominator != 1:
        return None
    return int(number.numerator)


def _literal_fraction(expr: Expr) -> Fraction | None:
    if expr.num is None:
        return None
    try:
        return bounded_number(expr.num)
    except EngineUnsupported:
        return None


def _is_zero_literal(expr: Expr) -> bool:
    return _literal_fraction(expr) == 0


def _clamp_degree(value: int) -> int:
    return _TERM_OVERFLOW if value > MAX_OUTPUT_TERMS else value


_ZERO = Expr(num="0")
_ONE = Expr(num="1")
_NEGATIVE_ONE = Expr(num="-1")
_Key = tuple[Any, ...]


def _leaf_key(expr: Expr) -> _Key:
    if expr.num is not None:
        value = _literal_fraction(expr)
        return ("num", value) if value is not None else ("raw", expr.num)
    if expr.sym is not None:
        return ("sym", expr.sym)
    return ("param", expr.param)


def _signed_product_key(sign: int, base: Expr, base_key: _Key) -> _Key:
    if sign > 0:
        return base_key
    return ("op", "mul", (("num", Fraction(-1)), base_key))


def _split_sign(
    expr: Expr,
    sign: int,
    key: _Key,
    key_by_id: dict[int, _Key],
) -> list[tuple[int, Expr, _Key]]:
    """Split a term into a sign and an unsigned base.

    Negative literal factors, negative numeric literals and subtraction are
    normalised into the sign so structurally opposite terms share one key.
    """
    if expr.op == "mul":
        factors: list[Expr] = []
        flips = 0
        for factor in expr.args:
            if factor.num is not None and _literal_integer(factor) == -1:
                flips += 1
            else:
                factors.append(factor)
        if flips:
            sign = -sign if flips % 2 else sign
            if not factors:
                return [(sign, _ONE, ("num", Fraction(1)))]
            if len(factors) == 1:
                base = factors[0]
                return [(sign, base, key_by_id[id(base)])]
            base = Expr(op="mul", args=factors)
            base_key = ("op", "mul", tuple(key_by_id[id(factor)] for factor in factors))
            key_by_id[id(base)] = base_key
            return [(sign, base, base_key)]
    if expr.num is not None:
        value = _literal_fraction(expr)
        if value is not None and value < 0:
            positive = Expr(num=str(-value))
            positive_key = ("num", -value)
            key_by_id[id(positive)] = positive_key
            return [(-sign, positive, positive_key)]
    return [(sign, expr, key)]


@dataclass
class _FlatAdd:
    """Deferred addition: flattening a deep chain is linear at the root."""

    parts: list[tuple[Any, int]]


def _materialise(
    value: Any,
    key_by_id: dict[int, _Key],
    materialised: dict[int, tuple[Expr, _Key]],
) -> tuple[Expr, _Key]:
    """Turn a deferred addition (and its children) into a normalised tree."""
    if isinstance(value, Expr):
        return value, key_by_id[id(value)]
    cached = materialised.get(id(value))
    if cached is not None:
        return cached
    terms: list[tuple[int, Expr, _Key]] = []
    stack: list[tuple[Any, int]] = list(reversed(value.parts))
    while stack:
        child, sign = stack.pop()
        if isinstance(child, _FlatAdd):
            for part, part_sign in reversed(child.parts):
                stack.append((part, sign * part_sign))
            continue
        if child.op in {"add", "sub"}:
            args = child.args
            signs = [1, -1] if child.op == "sub" and len(args) == 2 else [1] * len(args)
            for argument, argument_sign in reversed(
                list(zip(args, signs, strict=True))
            ):
                stack.append((argument, sign * argument_sign))
            continue
        terms.extend(_split_sign(child, sign, key_by_id[id(child)], key_by_id))
    result, result_key = _build_add(terms, key_by_id)
    key_by_id[id(result)] = result_key
    materialised[id(value)] = (result, result_key)
    return result, result_key


def _build_add(
    terms: list[tuple[int, Expr, _Key]],
    key_by_id: dict[int, _Key],
) -> tuple[Expr, _Key]:
    terms = [term for term in terms if not _is_zero_literal(term[1])]
    if not terms:
        return _ZERO, ("num", Fraction(0))
    positive: dict[_Key, int] = {}
    negative: dict[_Key, int] = {}
    for sign, _base, key in terms:
        counts = positive if sign > 0 else negative
        counts[key] = counts.get(key, 0) + 1
    cancelled = {
        key: min(count, negative.get(key, 0))
        for key, count in positive.items()
        if key in negative
    }
    survivors: list[tuple[int, Expr, _Key]] = []
    remaining_positive = dict(cancelled)
    remaining_negative = dict(cancelled)
    for sign, base, key in terms:
        remaining = remaining_positive if sign > 0 else remaining_negative
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
            continue
        survivors.append((sign, base, key))
    if not survivors:
        return _ZERO, ("num", Fraction(0))
    if len(survivors) == 1:
        sign, base, key = survivors[0]
        if sign > 0:
            return base, key
        wrapped = Expr(op="mul", args=[_NEGATIVE_ONE, base])
        wrapped_key = _signed_product_key(sign, base, key)
        key_by_id[id(wrapped)] = wrapped_key
        return wrapped, wrapped_key
    arguments: list[Expr] = []
    keys: list[_Key] = []
    for sign, base, key in survivors:
        if sign > 0:
            arguments.append(base)
            keys.append(key)
        else:
            wrapped = Expr(op="mul", args=[_NEGATIVE_ONE, base])
            wrapped_key = _signed_product_key(sign, base, key)
            key_by_id[id(wrapped)] = wrapped_key
            arguments.append(wrapped)
            keys.append(wrapped_key)
    return Expr(op="add", args=arguments), ("op", "add", tuple(keys))


def _normalise_node(
    node: Expr,
    children: list[Any],
    key_by_id: dict[int, _Key],
    materialised: dict[int, tuple[Expr, _Key]],
) -> tuple[Any, _Key | None]:
    op = node.op
    if op is None:
        return node, _leaf_key(node)
    if op == "add":
        return _FlatAdd([(child, 1) for child in children]), None
    if op == "sub" and len(children) == 2:
        return _FlatAdd([(children[0], 1), (children[1], -1)]), None
    resolved = [_materialise(child, key_by_id, materialised) for child in children]
    children = [child for child, _key in resolved]
    child_keys = [key for _child, key in resolved]
    if op == "mul":
        factors: list[Expr] = []
        for child in children:
            if child.op == "mul":
                factors.extend(child.args)
            else:
                factors.append(child)
        kept: list[Expr] = []
        for factor in factors:
            value = _literal_fraction(factor)
            if value == 0:
                return _ZERO, ("num", Fraction(0))
            if value == 1:
                continue
            kept.append(factor)
        if not kept:
            return _ONE, ("num", Fraction(1))
        if len(kept) == 1:
            single = kept[0]
            return single, key_by_id[id(single)]
        return Expr(op="mul", args=kept), (
            "op",
            "mul",
            tuple(key_by_id[id(factor)] for factor in kept),
        )
    if op == "pow":
        base = children[0]
        exponent = _literal_integer(children[1]) if len(children) == 2 else None
        if exponent == 0 or _literal_fraction(base) == 1:
            return _ONE, ("num", Fraction(1))
        if exponent is not None and exponent > 0 and _literal_fraction(base) == 0:
            return _ZERO, ("num", Fraction(0))
        if exponent == 1:
            return base, child_keys[0]
        return Expr(op="pow", args=children), ("op", "pow", tuple(child_keys))
    if op == "div" and len(children) == 2:
        numerator, denominator = children
        if child_keys[0] == child_keys[1] and not _is_zero_literal(numerator):
            return _ONE, ("num", Fraction(1))
        return Expr(op="div", args=children), ("op", "div", tuple(child_keys))
    return Expr(op=op, args=children), ("op", op, tuple(child_keys))


def normalise_expression(expr: Expr) -> Expr:
    """Cancel cheap structural noise before estimating expansion size.

    The rewrite is value-preserving for the supported real-domain trees:
    ``add``/``sub`` are flattened, identical opposite terms are cancelled,
    literal zeros are dropped, ``mul`` is flattened and its literal ones and
    zeros are removed, ``pow`` by zero or one is unwrapped, and ``div(a, a)``
    collapses to one. It is iterative and memoised, so adversarial trees
    cannot exhaust the recursion limit or cause exponential re-traversal.
    """
    return _normalise_with_keys(expr)[0]


def _normalise_with_keys(expr: Expr) -> tuple[Expr, dict[int, _Key]]:
    resolved: dict[int, Any] = {}
    key_by_id: dict[int, _Key] = {
        id(_ZERO): ("num", Fraction(0)),
        id(_ONE): ("num", Fraction(1)),
        id(_NEGATIVE_ONE): ("num", Fraction(-1)),
    }
    materialised: dict[int, tuple[Expr, _Key]] = {}
    pending: list[tuple[Expr, bool]] = [(expr, False)]
    while pending:
        node, children_done = pending.pop()
        key = id(node)
        if key in resolved:
            continue
        if not children_done:
            pending.append((node, True))
            for child in node.args:
                if id(child) not in resolved:
                    pending.append((child, False))
            continue
        children = [resolved[id(child)] for child in node.args]
        normalised, normalised_key = _normalise_node(
            node, children, key_by_id, materialised
        )
        resolved[key] = normalised
        if isinstance(normalised, Expr) and normalised_key is not None:
            key_by_id[id(normalised)] = normalised_key
    normalised_root, _root_key = _materialise(
        resolved[id(expr)], key_by_id, materialised
    )
    return normalised_root, key_by_id


def _multinomial_terms(exponent: int, base_terms: int) -> int:
    """C(exponent + base_terms - 1, base_terms - 1), clamped early."""
    if exponent <= 0:
        return 1
    if base_terms <= 1:
        return 1
    if base_terms > MAX_OUTPUT_TERMS:
        return _TERM_OVERFLOW
    total = 1
    for step in range(1, base_terms):
        total = total * (exponent + step) // step
        if total > MAX_OUTPUT_TERMS:
            return _TERM_OVERFLOW
    return total


def _node_terms(expr: Expr, child_terms: list[int]) -> int:
    operation = expr.op
    if operation is None:
        return 1
    if operation == "mul":
        total = 1
        for child in child_terms:
            if child > 1 and total > MAX_OUTPUT_TERMS // child:
                return _TERM_OVERFLOW
            total *= child
        return _clamp_terms(total)
    if operation == "div":
        # A rational function carries the product of its numerator and
        # denominator expansions, not their sum.
        total = 1
        for child in child_terms[:2]:
            if child > 1 and total > MAX_OUTPUT_TERMS // child:
                return _TERM_OVERFLOW
            total *= child
        return _clamp_terms(total)
    if operation == "pow":
        base = child_terms[0] if child_terms else 1
        exponent = _literal_integer(expr.args[1]) if len(expr.args) == 2 else None
        if exponent is None:
            # Rational and symbolic exponents do not expand into a polynomial.
            return base
        # A negative integer exponent expands to a rational function whose
        # numerator and denominator carry the same multinomial growth as the
        # positive power, so bound it by the magnitude of the exponent.
        return _multinomial_terms(abs(exponent), base)
    # add, sub and unary functions all add their children's term counts.
    total = 0
    for child in child_terms:
        total += child
        if total > MAX_OUTPUT_TERMS:
            return _TERM_OVERFLOW
    return total


def _estimated_terms_normalised(expr: Expr) -> int:
    """Estimate a normalised tree; clamped and iterative."""
    resolved: dict[int, int] = {}
    pending: list[tuple[Expr, bool]] = [(expr, False)]
    while pending:
        node, children_done = pending.pop()
        key = id(node)
        if key in resolved:
            continue
        if not children_done:
            pending.append((node, True))
            for child in node.args:
                if id(child) not in resolved:
                    pending.append((child, False))
            continue
        resolved[key] = _node_terms(node, [resolved[id(child)] for child in node.args])
    return resolved[id(expr)]


def estimated_terms(expr: Expr) -> int:
    """Conservative, cheap estimate of the expanded term count, clamped.

    The expression is structurally normalised first, so cancelling expansions
    are measured by what remains. The traversal is iterative and stops
    accumulating as soon as the estimate exceeds ``MAX_OUTPUT_TERMS``, so
    adversarial trees cannot build huge integers or exhaust the recursion
    limit.
    """
    return _estimated_terms_normalised(normalise_expression(expr))


def _has_rational_structure(expr: Expr) -> bool:
    """Whether the normalised tree contains division or a negative power."""
    pending = [expr]
    seen: set[int] = set()
    while pending:
        node = pending.pop()
        key = id(node)
        if key in seen:
            continue
        seen.add(key)
        if node.op == "div":
            return True
        if node.op == "pow" and len(node.args) == 2:
            exponent = _literal_integer(node.args[1])
            if exponent is not None and exponent < 0:
                return True
        pending.extend(node.args)
    return False


def total_degree(expr: Expr) -> int:
    """Total polynomial degree, counting numerator plus denominator degree.

    Division and negative powers add both sides' degrees because a rational
    function's expanded work grows with both. The result is clamped so
    adversarial exponents cannot build enormous integers.
    """
    resolved: dict[int, int] = {}
    pending: list[tuple[Expr, bool]] = [(expr, False)]
    while pending:
        node, children_done = pending.pop()
        key = id(node)
        if key in resolved:
            continue
        if not children_done:
            pending.append((node, True))
            for child in node.args:
                if id(child) not in resolved:
                    pending.append((child, False))
            continue
        child_degrees = [resolved[id(child)] for child in node.args]
        if node.op is None:
            degree = 0 if node.num is not None else 1
        elif node.op in {"add", "sub"}:
            degree = max(child_degrees, default=0)
        elif node.op in {"mul", "div"}:
            degree = _clamp_degree(sum(child_degrees))
        elif node.op == "pow" and len(node.args) == 2:
            exponent = _literal_integer(node.args[1])
            base = child_degrees[0] if child_degrees else 0
            if exponent is None:
                degree = base
            elif exponent == 0:
                degree = 0
            else:
                degree = _clamp_degree(abs(exponent) * base)
        else:
            degree = max(child_degrees, default=0)
        resolved[key] = degree
    return resolved[id(expr)]


def require_bounded_terms(expr: Expr) -> None:
    """Reject an expression whose expansion or rational work exceeds budget."""
    normalised = normalise_expression(expr)
    estimate = _estimated_terms_normalised(normalised)
    if estimate > MAX_OUTPUT_TERMS:
        raise EngineUnsupported(
            f"expression expansion exceeds the {MAX_OUTPUT_TERMS}-term output budget"
        )
    if _has_rational_structure(normalised):
        degree = total_degree(normalised)
        if estimate * (degree + 1) > MAX_OUTPUT_TERMS:
            raise EngineUnsupported(
                "rational expression work exceeds the "
                f"{MAX_OUTPUT_TERMS}-term output budget"
            )


def validate_request(request: CorrectnessRequest) -> None:
    """Reject unsupported trees and malformed references without running SymPy."""
    names = {symbol.name for symbol in request.problem.symbols}
    nodes = 0
    expression_nodes = 0

    def visit(expr: Expr, depth: int = 0) -> tuple[int, int]:
        nonlocal nodes, expression_nodes
        if depth == 0:
            expression_nodes = 0
            require_bounded_terms(expr)
        nodes += 1
        expression_nodes += 1
        if nodes > MAX_TOTAL_NODES or expression_nodes > 200 or depth > MAX_DEPTH:
            raise EngineUnsupported("expression exceeds node or depth budget")
        if expr.num is not None:
            number = bounded_number(expr.num)
            return max(
                number.numerator.bit_length(), number.denominator.bit_length()
            ), 0
        elif expr.sym is not None:
            if expr.sym not in names:
                raise ValueError(f"undeclared symbol {expr.sym!r}")
            return 1, 1
        elif expr.param is not None:
            raise ValueError("concrete requests cannot contain unbound parameters")
        else:
            if expr.op not in _ARITY:
                raise EngineUnsupported(f"unsupported operator {expr.op!r}")
            low, high = _ARITY[expr.op]
            if not low <= len(expr.args) <= high:
                raise ValueError(f"operator {expr.op!r} has invalid arity")
            if expr.op == "pow":
                exponent = expr.args[1]
                if exponent.num is None:
                    raise EngineUnsupported("powers require a bounded literal exponent")
                power = bounded_number(exponent.num)
                if abs(power) > 12 or power.denominator > 12:
                    raise EngineUnsupported("power exceeds exponent budget")
            children = [visit(child, depth + 1) for child in expr.args]
            bits = sum(child[0] for child in children) + 1
            degree = max(child[1] for child in children)
            if expr.op == "mul":
                degree = sum(child[1] for child in children)
            if expr.op == "pow":
                multiplier = max(1, abs(power.numerator))
                bits = children[0][0] * multiplier
                degree = children[0][1] * multiplier
            if bits > 4096 or degree > 128:
                raise EngineUnsupported("expression exceeds intermediate growth budget")
            return bits, degree

    def matrix(value: list[list[Expr]] | None) -> None:
        if value is None:
            return
        if not value or len(value) > MAX_MATRIX_DIMENSION:
            raise EngineUnsupported("matrix exceeds dimension budget or is empty")
        columns = len(value[0])
        if not 1 <= columns <= MAX_MATRIX_DIMENSION or any(
            len(row) != columns for row in value
        ):
            raise ValueError(
                "matrix must be nonempty, rectangular and within dimension limits"
            )
        for row in value:
            for cell in row:
                visit(cell)

    problem, answer = request.problem, request.answer
    for expr in (problem.expression, problem.lower, problem.upper, answer.expression):
        if expr is not None:
            visit(expr)
    for relation in problem.relations:
        visit(relation.lhs)
        visit(relation.rhs)
    for expr in answer.items:
        visit(expr)
    for interval in answer.intervals:
        for endpoint in (interval.lower, interval.upper):
            if endpoint is not None:
                visit(endpoint)
    for value in (
        problem.matrix,
        problem.right_matrix,
        answer.matrix,
        answer.permutation,
        answer.lower,
        answer.upper,
    ):
        matrix(value)
    if problem.operation == "solve":
        candidate_values = list(answer.items)
        if answer.expression is not None:
            candidate_values.append(answer.expression)
        for interval in answer.intervals:
            candidate_values.extend(
                endpoint
                for endpoint in (interval.lower, interval.upper)
                if endpoint is not None
            )
        if any(_has_symbol(expr) for expr in candidate_values):
            raise EngineUnknown(
                "solution values require closed expressions; "
                "symbolic candidate domain is unresolved"
            )
        targets = set(problem.solve_for)
        for relation in problem.relations:
            if relation.kind in {"lt", "le", "gt", "ge"} and (
                _has_periodic_variable(relation.lhs, targets)
                or _has_periodic_variable(relation.rhs, targets)
            ):
                raise EngineUnsupported(
                    "trigonometric inequalities require a qualified periodic solver"
                )
    if problem.operation != "solve" and problem.relations:
        raise EngineUnsupported(
            "relational givens are currently supported only for solve"
        )
    # Matrices are an exact numeric capability; avoid evaluation erasing symbolic holes.
    if (
        problem.operation in {"matrix-multiply", "determinant", "inverse", "lu"}
        and names
    ):
        raise EngineUnsupported(
            "matrix entries currently require exact numeric expressions"
        )


def _has_periodic_variable(expr: Expr, targets: set[str]) -> bool:
    def has_target(node: Expr) -> bool:
        return node.sym in targets or any(has_target(child) for child in node.args)

    return (expr.op in {"sin", "cos", "tan"} and has_target(expr)) or any(
        _has_periodic_variable(child, targets) for child in expr.args
    )


def _has_symbol(expr: Expr) -> bool:
    return expr.sym is not None or any(_has_symbol(child) for child in expr.args)
