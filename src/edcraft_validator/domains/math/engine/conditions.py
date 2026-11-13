"""One source of original-AST real-domain guards for all engine handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import sympy

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import EngineUnsupported
from edcraft_validator.domains.math.ir.compile import MathCompileError, parse_exact
from edcraft_validator.domains.math.ir.schema import Expr, SymbolSpec

ConditionKind = Literal["ne", "gt", "ge", "lt", "le"]


@dataclass(frozen=True)
class Condition:
    kind: ConditionKind
    expr: sympy.Expr

    def substitute(self, values: dict[sympy.Symbol, sympy.Expr]) -> Condition:
        return Condition(self.kind, sympy.sympify(self.expr).subs(values))


_KNOWN_AST_OPERATORS = frozenset(
    {
        "add",
        "sub",
        "mul",
        "div",
        "pow",
        "sqrt",
        "abs",
        "exp",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "log",
    }
)


def compile_ast(ctx: EngineContext, expr: Expr | None) -> sympy.Expr:
    """Compile a validated IR node, translating compiler failures honestly."""
    if expr is None:
        raise EngineUnsupported("missing expression")
    try:
        return ctx.compile(expr)
    except (MathCompileError, TypeError, ValueError) as exc:
        raise EngineUnsupported(f"expression cannot be compiled: {exc}") from exc


def ast_conditions(ctx: EngineContext, root: Expr) -> tuple[Condition, ...]:
    """Collect the real-domain guards present in the original AST.

    Collection deliberately walks every raw denominator, square root, negative
    power, log, inverse trig and tangent node before SymPy can cancel it.
    """
    conditions: list[Condition] = []
    compiled: dict[int, sympy.Expr] = {}

    def compile_node(node: Expr) -> sympy.Expr:
        key = id(node)
        if key not in compiled:
            compiled[key] = compile_ast(ctx, node)
        return compiled[key]

    def walk(node: Expr) -> None:
        op = node.op
        if op is None:
            return
        if op not in _KNOWN_AST_OPERATORS:
            raise EngineUnsupported(f"unsupported scalar operator {op!r}")
        args = node.args
        if op == "div":
            _require_arity(op, args, 2)
            conditions.append(Condition("ne", compile_node(args[1])))
        elif op == "sqrt":
            _require_arity(op, args, 1)
            conditions.append(Condition("ge", compile_node(args[0])))
        elif op == "log":
            if len(args) == 1:
                conditions.append(Condition("gt", compile_node(args[0])))
            elif len(args) == 2:
                base = compile_node(args[1])
                conditions.append(Condition("gt", compile_node(args[0])))
                conditions.append(Condition("gt", base))
                conditions.append(Condition("ne", base - 1))
            else:
                raise EngineUnsupported("log requires one or two arguments")
        elif op == "pow":
            _require_arity(op, args, 2)
            base = compile_node(args[0])
            exponent = _compile_exponent(ctx, args[1])
            power_conditions(base, exponent, conditions)
        elif op == "tan":
            _require_arity(op, args, 1)
            conditions.append(Condition("ne", sympy.cos(compile_node(args[0]))))
        elif op in {"asin", "acos"}:
            _require_arity(op, args, 1)
            argument = compile_node(args[0])
            conditions.append(Condition("ge", argument + 1))
            conditions.append(Condition("le", argument - 1))
        for child in args:
            walk(child)

    walk(root)
    return tuple(dict.fromkeys(conditions))


def _require_arity(operator: str, args: list[Expr], arity: int) -> None:
    if len(args) != arity:
        raise EngineUnsupported(f"{operator} requires {arity} arguments")


def _compile_exponent(ctx: EngineContext, node: Expr) -> sympy.Expr:
    if node.num is not None:
        value = parse_exact(node.num)
        return sympy.Rational(value.numerator, value.denominator)
    exponent = compile_ast(ctx, node)
    if not exponent.is_number or exponent.is_real is not True:
        raise EngineUnsupported("powers require an exact real exponent")
    return exponent


def power_conditions(
    base: sympy.Expr,
    exponent: sympy.Expr,
    conditions: list[Condition],
) -> None:
    if exponent.is_zero is True:
        return
    if exponent.is_Integer:
        if exponent < 0:
            conditions.append(Condition("ne", base))
        return
    if exponent.is_Rational:
        # The shared IR compiler uses SymPy's principal power. Its real branch
        # requires a nonnegative base even for odd denominators. A distinct
        # real-root operator would need a different compilation contract.
        conditions.append(Condition("gt" if exponent < 0 else "ge", base))
        return
    if exponent.is_positive is True:
        conditions.append(Condition("ge", base))
    elif exponent.is_negative is True:
        conditions.append(Condition("gt", base))
    else:
        raise EngineUnsupported("cannot determine the real domain of a power")


def symbol_domain(spec: SymbolSpec, requested: str = "real") -> sympy.Set:
    domains = {
        "real": sympy.S.Reals,
        "integer": sympy.S.Integers,
        "rational": sympy.S.Rationals,
    }
    domain = domains[requested].intersect(domains[spec.domain])
    if spec.integer:
        domain = domain.intersect(sympy.S.Integers)
    if spec.positive:
        domain = domain.intersect(sympy.Interval.open(0, sympy.oo))
    if spec.nonzero:
        domain = domain - sympy.FiniteSet(0)
    return domain
