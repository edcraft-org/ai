"""Bound closed requests before any potentially expensive symbolic computation."""

from __future__ import annotations

import re
from fractions import Fraction

from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    EngineUnsupported,
)
from edcraft_validator.domains.math.ir.schema import Expr

MAX_TOTAL_NODES = 1000
MAX_DEPTH = 24
MAX_MATRIX_DIMENSION = 8
MAX_LITERAL_BITS = 512
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


def validate_request(request: CorrectnessRequest) -> None:
    """Reject unsupported trees and malformed references without running SymPy."""
    names = {symbol.name for symbol in request.problem.symbols}
    nodes = 0
    expression_nodes = 0

    def visit(expr: Expr, depth: int = 0) -> tuple[int, int]:
        nonlocal nodes, expression_nodes
        if depth == 0:
            expression_nodes = 0
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
