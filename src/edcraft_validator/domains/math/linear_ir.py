"""Adapt the legacy linear template to the typed math IR.

The wire contract still accepts ``a*x + b = c`` templates. This adapter projects
that fixed shape into the generic IR so one solver and one harness validate it;
it does not accept any new model-authored syntax.
"""

from __future__ import annotations

import ast
from fractions import Fraction

from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    PrimitiveSpec,
    Relation,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.math_schemas import MathTemplateCandidate
from edcraft_validator.domains.math.math_types import MATH_PARAMETER_NAMES
from edcraft_validator.domains.math.safe_linear import validate_expression

MAX_IR_VARIANTS = 512


def linear_template_ir(candidate: MathTemplateCandidate) -> MathTemplateSpec:
    """Convert a checked canonical linear template into a parameterised IR."""
    if (
        candidate.parameters is None
        or candidate.distractors is None
        or candidate.question_template is None
    ):
        raise ValueError("linear templates require the legacy authoring fields")
    parameters = {
        parameter.name: [str(value) for value in parameter.values]
        for parameter in candidate.parameters
    }
    if set(parameters) != set(MATH_PARAMETER_NAMES):
        raise ValueError("linear templates must declare exactly a, b, and c")

    body = MathItemSpec(
        topic="school.linear_equation",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[
            Given(
                id="equation",
                relation=Relation(
                    kind="eq",
                    lhs=_add(
                        _mul(_param("a"), _sym("x")),
                        _param("b"),
                    ),
                    rhs=_param("c"),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x", domain="real"),
        distractors=[
            Distractor(
                value=_expression_ir(recipe.expression),
                misconception=_misconception_tag(recipe.reason_template),
                reason=recipe.reason_template,
            )
            for recipe in candidate.distractors
        ],
        text=TextSpec(mode="symbolic", template=candidate.question_template),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )
    return MathTemplateSpec(
        topic="school.linear_equation",
        parameters=[
            ParameterSpec(name=name, values=values)
            for name, values in parameters.items()
        ],
        body=body,
    )


def _expression_ir(expression: str) -> Expr:
    validate_expression(expression)
    return _from_ast(ast.parse(expression, mode="eval").body)


def _from_ast(node: ast.AST) -> Expr:
    if isinstance(node, ast.Constant):
        if type(node.value) is int:
            return _num(str(node.value))
        return _num(str(Fraction(str(node.value))))
    if isinstance(node, ast.Name):
        if node.id == "x":
            return _sym("x")
        return _param(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _sub(_num("0"), _from_ast(node.operand))
    if isinstance(node, ast.BinOp):
        left = _from_ast(node.left)
        right = _from_ast(node.right)
        if isinstance(node.op, ast.Add):
            return _add(left, right)
        if isinstance(node.op, ast.Sub):
            return _sub(left, right)
        if isinstance(node.op, ast.Mult):
            return _mul(left, right)
        if isinstance(node.op, ast.Div):
            return _div(left, right)
    raise ValueError(f"unsupported linear expression node {type(node).__name__}")


def _num(value: str) -> Expr:
    return Expr(num=value)


def _sym(name: str) -> Expr:
    return Expr(sym=name)


def _param(name: str) -> Expr:
    return Expr(param=name)


def _add(*args: Expr) -> Expr:
    return Expr(op="add", args=list(args))


def _mul(*args: Expr) -> Expr:
    return Expr(op="mul", args=list(args))


def _sub(left: Expr, right: Expr) -> Expr:
    return Expr(op="sub", args=[left, right])


def _div(left: Expr, right: Expr) -> Expr:
    return Expr(op="div", args=[left, right])


def _misconception_tag(reason: str) -> str:
    """Keep a stable tag while the legacy reason text stays wire-compatible."""
    compact = "_".join(reason.upper().split())
    return compact[:80] or "UNSPECIFIED"
