"""Render one finite math IR template into learner-facing text and choices.

The template body is data: parameter nodes are the only variation point. This
module substitutes declared values for display and compilation, and it renders
the reserved placeholders ``expr``, ``equation``, ``equations`` and ``matrix``.
It never executes model-authored code.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from string import Formatter

import sympy
from sympy.matrices.matrixbase import MatrixBase

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
    parse_exact,
)
from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Expr,
    MathItemSpec,
    MathTemplateSpec,
    Relation,
)
from edcraft_validator.text_templates import render_text_template, template_fields


def fraction_text(value: Fraction | int) -> str:
    """Render an exact value without a trailing decimal or float conversion."""
    fraction = value if isinstance(value, Fraction) else Fraction(value)
    if fraction.denominator == 1:
        return str(fraction.numerator)
    return f"{fraction.numerator}/{fraction.denominator}"


def _latex_number(value: Fraction | int) -> str:
    """Typeset an exact value, keeping fractions as stacked fractions."""
    fraction = value if isinstance(value, Fraction) else Fraction(value)
    return sympy.latex(sympy.Rational(fraction.numerator, fraction.denominator))


def render_expr(value: sympy.Expr) -> str:
    """Render an exact SymPy value in the lightweight notation used in prompts."""
    return sympy.sstr(value).replace("**", "^")


_PRECEDENCE = {"add": 1, "sub": 1, "mul": 2, "div": 2, "pow": 3}
_FUNCTION_OPS = {
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


def render_authored_expr(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Render an authored expression tree without folding it to a value.

    The engine compiles a separate tree for grading; learner-facing text keeps
    the structure the model authored. A constant expression such as ``12 + 14``
    therefore stays visible instead of collapsing to ``26`` before the learner
    sees it.
    """
    # Compilation limits the tree and rejects unknown symbols or parameters.
    compile_expr(expr, symbols, params)
    return _render_authored(expr, symbols, params or {})


def _render_authored(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> str:
    if expr.num is not None:
        return fraction_text(parse_exact(expr.num))
    if expr.sym is not None:
        if expr.sym not in symbols:
            raise MathCompileError(f"unknown symbol {expr.sym!r}")
        return expr.sym
    if expr.param is not None:
        try:
            return fraction_text(params[expr.param])
        except KeyError as exc:
            raise MathCompileError(f"unbound parameter {expr.param!r}") from exc
    if expr.op is None:
        raise MathCompileError("expression node has no kind")
    if expr.op in _PRECEDENCE:
        return _render_operator(expr.op, expr.args, symbols, params)
    if expr.op in _FUNCTION_OPS:
        arity = {1, 2} if expr.op == "log" else {1}
        if len(expr.args) not in arity:
            raise MathCompileError(f"operator {expr.op!r} has the wrong arity")
        arguments = ", ".join(
            _render_authored(child, symbols, params) for child in expr.args
        )
        return f"{expr.op}({arguments})"
    raise MathCompileError(f"unsupported operator {expr.op!r}")


def _render_operator(
    op: str,
    args: list[Expr],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> str:
    if op in {"add", "mul"}:
        if not args:
            raise MathCompileError(f"operator {op!r} requires arguments")
    elif len(args) != 2:
        raise MathCompileError(f"operator {op!r} requires two arguments")
    rendered = [_render_authored(child, symbols, params) for child in args]
    if op == "add":
        terms: list[str] = []
        for index, (child, text) in enumerate(zip(args, rendered, strict=True)):
            if child.op == "sub":
                text = f"({text})"
            if index == 0:
                terms.append(text)
            elif text.startswith("-"):
                terms.append(f" - {text[1:]}")
            else:
                terms.append(f" + {text}")
        return "".join(terms)
    if op == "sub":
        left, right = rendered
        if args[0].op == "sub":
            left = f"({left})"
        if args[1].op in {"add", "sub"}:
            right = f"({right})"
        elif right.startswith("-"):
            return f"{left} + {right[1:]}"
        return f"{left} - {right}"
    if op == "mul":
        parts: list[str] = []
        for index, (child, text) in enumerate(zip(args, rendered, strict=True)):
            if child.op in {"add", "sub", "div"}:
                text = f"({text})"
            if index and text.startswith("-"):
                text = f"({text})"
            parts.append(text)
        return "*".join(parts)
    if op == "div":
        left, right = rendered
        if args[0].op in {"add", "sub", "div"}:
            left = f"({left})"
        if args[1].op in {"add", "sub", "mul", "div", "pow"} or right.startswith("-"):
            right = f"({right})"
        return f"{left}/{right}"
    base, exponent = rendered
    if args[0].op in {"add", "sub", "mul", "div", "pow"} or base.startswith("-"):
        base = f"({base})"
    simple_exponent = (
        args[1].op is None
        and not exponent.startswith("-")
        and "/" not in exponent
        and "^" not in exponent
    )
    if not simple_exponent:
        exponent = f"({exponent})"
    return f"{base}^{exponent}"


def render_authored_expr_latex(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Typeset an authored expression tree without folding it to a value.

    The tree is walked like ``render_authored_expr`` so the LaTeX keeps the
    authored order and structure instead of collapsing ``12 + 14`` to ``26``.
    Only leaves go through SymPy.
    """
    # Compilation limits the tree and rejects unknown symbols or parameters.
    compile_expr(expr, symbols, params)
    return _render_authored_latex(expr, symbols, params or {})


def _render_authored_latex(
    expr: Expr,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> str:
    if expr.num is not None:
        return _latex_number(parse_exact(expr.num))
    if expr.sym is not None:
        if expr.sym not in symbols:
            raise MathCompileError(f"unknown symbol {expr.sym!r}")
        return sympy.latex(symbols[expr.sym])
    if expr.param is not None:
        try:
            return _latex_number(params[expr.param])
        except KeyError as exc:
            raise MathCompileError(f"unbound parameter {expr.param!r}") from exc
    if expr.op is None:
        raise MathCompileError("expression node has no kind")
    if expr.op in _PRECEDENCE:
        return _render_operator_latex(expr.op, expr.args, symbols, params)
    if expr.op in _FUNCTION_OPS:
        arity = {1, 2} if expr.op == "log" else {1}
        if len(expr.args) not in arity:
            raise MathCompileError(f"operator {expr.op!r} has the wrong arity")
        arguments = [
            _render_authored_latex(child, symbols, params) for child in expr.args
        ]
        return _render_function_latex(expr.op, arguments)
    raise MathCompileError(f"unsupported operator {expr.op!r}")


def _render_operator_latex(
    op: str,
    args: list[Expr],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction],
) -> str:
    if op in {"add", "mul"}:
        if not args:
            raise MathCompileError(f"operator {op!r} requires arguments")
    elif len(args) != 2:
        raise MathCompileError(f"operator {op!r} requires two arguments")
    rendered = [_render_authored_latex(child, symbols, params) for child in args]
    if op == "add":
        terms: list[str] = []
        for index, (child, text) in enumerate(zip(args, rendered, strict=True)):
            if child.op == "sub":
                text = rf"\left({text}\right)"
            if index == 0:
                terms.append(text)
            elif text.startswith("-"):
                terms.append(f" - {text[1:].lstrip()}")
            else:
                terms.append(f" + {text}")
        return "".join(terms)
    if op == "sub":
        left, right = rendered
        if args[0].op == "sub":
            left = rf"\left({left}\right)"
        if args[1].op in {"add", "sub"}:
            right = rf"\left({right}\right)"
        elif right.startswith("-"):
            return f"{left} + {right[1:].lstrip()}"
        return f"{left} - {right}"
    if op == "mul":
        parts: list[str] = []
        for index, (child, text) in enumerate(zip(args, rendered, strict=True)):
            if child.op in {"add", "sub", "div"}:
                text = rf"\left({text}\right)"
            if index and text.startswith("-"):
                text = rf"\left({text}\right)"
            parts.append(text)
        return r" \cdot ".join(parts)
    if op == "div":
        left, right = rendered
        return rf"\frac{{{left}}}{{{right}}}"
    base, exponent = rendered
    if args[0].op in {"add", "sub", "mul", "div", "pow"} or base.startswith("-"):
        base = rf"\left({base}\right)"
    simple_exponent = (
        args[1].op is None
        and not exponent.startswith("-")
        and "/" not in exponent
        and "^" not in exponent
    )
    if not simple_exponent:
        exponent = rf"\left({exponent}\right)"
    return f"{base}^{{{exponent}}}"


def _render_function_latex(op: str, arguments: list[str]) -> str:
    """Typeset one function call, mirroring the plain operator names."""
    first = arguments[0]
    if op == "sqrt":
        return rf"\sqrt{{{first}}}"
    if op == "abs":
        return rf"\left|{first}\right|"
    if op == "exp":
        return f"e^{{{first}}}"
    if op == "log":
        if len(arguments) == 2:
            return rf"\log_{{{arguments[1]}}}\left({first}\right)"
        return rf"\log\left({first}\right)"
    name = rf"\operatorname{{{op}}}" if op in {"asin", "acos", "atan"} else rf"\{op}"
    return rf"{name}\left({first}\right)"


def render_relation(
    relation: Relation,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Render a relation without evaluating it to a truth value.

    Parameter-only guards such as ``a != 0`` collapse to ``True``/``False``
    when both sides are substituted. Rendering the operands directly keeps the
    authored relation visible instead of raising on a missing ``lhs``.
    """
    operator = {
        "eq": "=",
        "ne": "≠",
        "lt": "<",
        "le": "≤",
        "gt": ">",
        "ge": "≥",
    }[relation.kind]

    lhs = render_expr(compile_expr(relation.lhs, symbols, params))
    rhs = render_expr(compile_expr(relation.rhs, symbols, params))
    return f"{lhs} {operator} {rhs}"


def _expr_has_symbol(expr: Expr | None) -> bool:
    if expr is None:
        return False
    if expr.sym is not None:
        return True
    return any(_expr_has_symbol(child) for child in expr.args)


def _relation_has_symbol(relation: Relation) -> bool:
    return _expr_has_symbol(relation.lhs) or _expr_has_symbol(relation.rhs)


def render_matrix(
    rows: list[list[Expr]],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    rendered = [
        "["
        + ", ".join(render_expr(compile_expr(cell, symbols, params)) for cell in row)
        + "]"
        for row in rows
    ]
    return "[" + ", ".join(rendered) + "]"


def render_relations(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> list[str]:
    """Render the symbol-bearing relations a learner would see.

    Relations that only mention substituted parameters are authoring guards
    (for example ``a != 0`` or ``a*d - b*c != 0``), not problem equations.
    """
    symbols = build_symbols(item.symbols)
    return [
        render_relation(given.relation, symbols, params)
        for given in item.givens
        if given.kind == "relation"
        and given.relation is not None
        and _relation_has_symbol(given.relation)
    ]


def render_relation_latex(
    relation: Relation,
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Typeset a relation from SymPy objects without evaluating its truth."""
    operators = {
        "eq": sympy.Eq,
        "ne": sympy.Ne,
        "lt": sympy.Lt,
        "le": sympy.Le,
        "gt": sympy.Gt,
        "ge": sympy.Ge,
    }
    lhs = compile_expr(relation.lhs, symbols, params)
    rhs = compile_expr(relation.rhs, symbols, params)
    return sympy.latex(operators[relation.kind](lhs, rhs, evaluate=False))


def render_relations_latex(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> list[str]:
    """Typeset the symbol-bearing relations a learner would see."""
    symbols = build_symbols(item.symbols)
    return [
        render_relation_latex(given.relation, symbols, params)
        for given in item.givens
        if given.kind == "relation"
        and given.relation is not None
        and _relation_has_symbol(given.relation)
    ]


def render_matrix_latex(
    rows: list[list[Expr]],
    symbols: Mapping[str, sympy.Symbol],
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Typeset a matrix from the compiled SymPy cells."""
    compiled = [[compile_expr(cell, symbols, params) for cell in row] for row in rows]
    return sympy.latex(sympy.Matrix(compiled))


def render_goal_display(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Render the mathematical object the learner is asked about."""
    relations = render_relations(item, params)
    if relations:
        return " and ".join(relations)
    symbols = build_symbols(item.symbols)
    if item.goal.kind == "evaluate":
        # An evaluate goal often encodes the arithmetic itself, so the authored
        # text is the problem and the solved value is not a display.
        return render_item_text(item, params)
    if item.goal.expr is not None:
        rendered = render_expr(compile_expr(item.goal.expr, symbols, params))
        if item.goal.kind in {"derivative", "integral"} and item.goal.symbol:
            return f"f({item.goal.symbol}) = {rendered}"
        return rendered
    if item.goal.matrix:
        return render_matrix(item.goal.matrix, symbols, params)
    return render_item_text(item, params)


def render_goal_display_latex(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> str | None:
    """Typeset the mathematical object the learner is asked about.

    Prose is never returned as LaTeX. A question whose prompt already carries
    the mathematics has no separate object to typeset and returns ``None``, so
    the frontend shows the plain equation instead.
    """
    relations = render_relations_latex(item, params)
    if relations:
        return r",\ ".join(relations)
    symbols = build_symbols(item.symbols)
    if item.goal.kind == "evaluate":
        # An evaluate goal often encodes the arithmetic itself, so the authored
        # text is the problem and the solved value is not a display.
        return None
    if item.goal.expr is not None:
        rendered = sympy.latex(compile_expr(item.goal.expr, symbols, params))
        if item.goal.kind in {"derivative", "integral"} and item.goal.symbol:
            return f"f({item.goal.symbol}) = {rendered}"
        return rendered
    if item.goal.matrix:
        return render_matrix_latex(item.goal.matrix, symbols, params)
    return None


def _text_values_latex(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> dict[str, str]:
    """Build the LaTeX substitution values for a text template."""
    fields = template_fields(item.text.template)
    values: dict[str, str] = {
        name: _latex_number(value) for name, value in (params or {}).items()
    }

    symbols = build_symbols(item.symbols)
    relations = render_relations_latex(item, params)
    if fields & {"expr"}:
        if item.goal.expr is None:
            raise ValueError("text template uses {{expr}} but the goal has none")
        values["expr"] = (
            render_authored_expr_latex(item.goal.expr, symbols, params)
            if item.goal.kind == "evaluate"
            else sympy.latex(compile_expr(item.goal.expr, symbols, params))
        )
    if fields & {"equation", "equations"}:
        if not relations:
            raise ValueError("text template uses an equation but the item has none")
        values["equation"] = relations[0]
        values["equations"] = r",\ ".join(relations)
    if "matrix" in fields:
        if not item.goal.matrix:
            raise ValueError("text template uses {{matrix}} but the goal has none")
        values["matrix"] = render_matrix_latex(item.goal.matrix, symbols, params)

    return values


def render_item_segments(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> list[tuple[str, str]]:
    """Split a filled prompt into prose and LaTeX pieces.

    Each placeholder becomes a ``math`` segment holding its typeset value and
    the surrounding words stay as ``text`` segments. A template with no
    placeholders yields one text segment.
    """
    source = item.text.template
    fields = template_fields(source)
    values = _text_values_latex(item, params)
    missing = fields - set(values)
    if missing:
        raise ValueError(
            "text template uses unknown placeholders: " + ", ".join(sorted(missing))
        )

    segments: list[tuple[str, str]] = []
    for literal, field_name, _, _ in Formatter().parse(source):
        if literal:
            segments.append(("text", literal))
        if field_name is not None:
            segments.append(("math", values[field_name]))
    if not segments:
        raise ValueError("rendered text must not be blank")
    return segments


def render_item_text_latex(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Fill a template's text, typesetting the placeholders as LaTeX."""
    return "".join(value for _, value in render_item_segments(item, params))


def render_item_text(
    item: MathItemSpec,
    params: Mapping[str, Fraction] | None = None,
) -> str:
    """Fill a template's learner-facing text without solving the item."""
    fields = template_fields(item.text.template)
    values: dict[str, str] = {
        name: fraction_text(value) for name, value in (params or {}).items()
    }

    symbols = build_symbols(item.symbols)
    relations = render_relations(item, params)
    if fields & {"expr"}:
        if item.goal.expr is None:
            raise ValueError("text template uses {{expr}} but the goal has none")
        values["expr"] = (
            render_authored_expr(item.goal.expr, symbols, params)
            if item.goal.kind == "evaluate"
            else render_expr(compile_expr(item.goal.expr, symbols, params))
        )
    if fields & {"equation", "equations"}:
        if not relations:
            raise ValueError("text template uses an equation but the item has none")
        values["equation"] = relations[0]
        values["equations"] = " and ".join(relations)
    if "matrix" in fields:
        if not item.goal.matrix:
            raise ValueError("text template uses {{matrix}} but the goal has none")
        values["matrix"] = render_matrix(item.goal.matrix, symbols, params)

    return render_text_template(item.text.template, values)


def substitute_expr(expr: Expr, params: Mapping[str, Fraction]) -> Expr:
    """Replace parameter nodes with exact numeric literals."""
    if expr.param is not None:
        try:
            value = params[expr.param]
        except KeyError as exc:
            raise ValueError(f"unbound parameter {expr.param!r}") from exc
        return Expr(num=fraction_text(value))
    if expr.op is None:
        return expr
    return expr.model_copy(
        update={"args": [substitute_expr(child, params) for child in expr.args]}
    )


def substitute_item(item: MathItemSpec, params: Mapping[str, Fraction]) -> MathItemSpec:
    """Return a concrete item with every parameter node replaced by its value."""
    givens = []
    for given in item.givens:
        relation = given.relation
        if relation is not None:
            relation = relation.model_copy(
                update={
                    "lhs": substitute_expr(relation.lhs, params),
                    "rhs": substitute_expr(relation.rhs, params),
                }
            )
        givens.append(given.model_copy(update={"relation": relation}))

    goal = item.goal.model_copy(
        update={
            "expr": (
                substitute_expr(item.goal.expr, params)
                if item.goal.expr is not None
                else None
            ),
            "point": (
                substitute_expr(item.goal.point, params)
                if item.goal.point is not None
                else None
            ),
            "matrix": (
                [
                    [substitute_expr(cell, params) for cell in row]
                    for row in item.goal.matrix
                ]
                if item.goal.matrix is not None
                else None
            ),
        }
    )

    distractors = [
        distractor.model_copy(
            update={
                "value": (
                    substitute_expr(distractor.value, params)
                    if distractor.value is not None
                    else None
                ),
                "items": [substitute_expr(entry, params) for entry in distractor.items],
                "components": [
                    substitute_expr(entry, params) for entry in distractor.components
                ],
            }
        )
        for distractor in item.distractors
    ]

    recipe = item.answer_recipe
    if recipe is not None:
        interval = recipe.interval
        if interval is not None:
            interval = interval.model_copy(
                update={
                    "lower": (
                        substitute_expr(interval.lower, params)
                        if interval.lower is not None
                        else None
                    ),
                    "upper": (
                        substitute_expr(interval.upper, params)
                        if interval.upper is not None
                        else None
                    ),
                }
            )
        recipe = recipe.model_copy(
            update={
                "items": [substitute_expr(entry, params) for entry in recipe.items],
                "interval": interval,
                "matrix": (
                    [
                        [substitute_expr(cell, params) for cell in row]
                        for row in recipe.matrix
                    ]
                    if recipe.matrix is not None
                    else None
                ),
            }
        )

    return item.model_copy(
        update={
            "givens": givens,
            "goal": goal,
            "distractors": distractors,
            "answer_recipe": recipe,
            "text": item.text.model_copy(
                update={"template": render_item_text(item, params)}
            ),
        }
    )


def declared_domain_size(template: MathTemplateSpec) -> int:
    """Return the Cartesian size of the declared domain without materialising it."""
    size = 1
    for parameter in template.parameters:
        size *= len(parameter.values)
    return size


def _combination_at(
    template: MathTemplateSpec, indices: tuple[int, ...]
) -> dict[str, Fraction] | None:
    """Parse one index tuple, or ``None`` when a declared value is not a literal."""
    try:
        return {
            parameter.name: Fraction(parameter.values[index])
            for parameter, index in zip(template.parameters, indices, strict=True)
        }
    except (ValueError, ZeroDivisionError):
        return None


def iter_parameter_combinations(
    template: MathTemplateSpec,
) -> Iterator[dict[str, Fraction]]:
    """Yield the finite parameter grid lazily, skipping invalid literals."""
    sizes = [len(parameter.values) for parameter in template.parameters]
    for indices in product(*(range(size) for size in sizes)):
        combination = _combination_at(template, indices)
        if combination is not None:
            yield combination


def parameter_combinations(
    template: MathTemplateSpec,
) -> list[dict[str, Fraction]]:
    """Materialise the finite parameter grid; only use this for small domains."""
    return list(iter_parameter_combinations(template))


@dataclass(frozen=True)
class SampledDomain:
    """A deterministic, bounded sample of a template's declared domain."""

    combinations: list[dict[str, Fraction]]
    declared_size: int
    whole_domain: bool


def _stable_index(seed: int, salt: str, size: int) -> int:
    payload = f"{seed}:{salt}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % size


def _boundary_indices(sizes: list[int]) -> Iterator[tuple[int, ...]]:
    """Cover each axis at both ends, with the other axes at both ends too."""
    yield tuple(0 for _ in sizes)
    yield tuple(size - 1 for size in sizes)
    for axis, size in enumerate(sizes):
        for edge in (0, size - 1):
            for other_edge in (0, 1):
                indices = [other_edge * (other - 1) for other in sizes]
                indices[axis] = edge
                yield tuple(indices)


def sample_parameter_combinations(
    template: MathTemplateSpec,
    *,
    limit: int,
    seed: int = 0,
) -> SampledDomain:
    """Sample a declared domain deterministically, including boundary cases.

    A domain that fits the budget is enumerated completely. Larger domains get
    one variant per axis edge followed by seeded examples, so neither the
    schema nor this function ever materialises the full product.
    """
    if limit < 1:
        raise ValueError("sample limit must be positive")
    declared_size = declared_domain_size(template)
    if declared_size <= limit:
        return SampledDomain(
            combinations=list(iter_parameter_combinations(template)),
            declared_size=declared_size,
            whole_domain=True,
        )

    sizes = [len(parameter.values) for parameter in template.parameters]
    selected: list[dict[str, Fraction]] = []
    seen: set[tuple[int, ...]] = set()

    def add(indices: tuple[int, ...]) -> None:
        if indices in seen or len(selected) >= limit:
            return
        combination = _combination_at(template, indices)
        if combination is None:
            return
        seen.add(indices)
        selected.append(combination)

    for indices in _boundary_indices(sizes):
        add(indices)

    attempt = 0
    # Invalid literals are rare; cap the retries so a domain made mostly of
    # unparseable values still terminates.
    max_attempts = limit * 32
    while len(selected) < limit and attempt < max_attempts:
        add(
            tuple(
                _stable_index(seed, f"variant:{attempt}:{axis}", size)
                for axis, size in enumerate(sizes)
            )
        )
        attempt += 1

    return SampledDomain(
        combinations=selected,
        declared_size=declared_size,
        whole_domain=len(selected) >= declared_size,
    )


def representative_item(
    template: MathTemplateSpec,
    *,
    limit: int = 16,
    seed: int = 0,
) -> MathItemSpec:
    """Instantiate the first renderable combination for a concrete check.

    Prose fidelity and blind parse-back operate on a concrete item, not on
    unbound parameter nodes. Symbolic templates use the same projection for
    consistency; their parse-back is skipped. The domain is sampled, never
    materialised.
    """
    sample = sample_parameter_combinations(template, limit=limit, seed=seed)

    for params in sample.combinations:
        try:
            return substitute_item(template.body, params)
        except (MathCompileError, ValueError, ZeroDivisionError):
            continue
    raise ValueError("template has no renderable parameter combination")


def display_sympy_value(value: object) -> str:
    """Render a solved value using the same notation as the question text."""
    if isinstance(value, MatrixBase):
        return (
            "[["
            + ", ".join(
                ", ".join(render_expr(cell) for cell in row) for row in value.tolist()
            )
            + "]]"
        )
    if isinstance(value, sympy.Tuple):
        return "(" + ", ".join(render_expr(item) for item in value) + ")"
    if isinstance(value, sympy.FiniteSet):
        items = sorted(value.args, key=sympy.default_sort_key)
        return "{" + ", ".join(display_sympy_value(item) for item in items) + "}"
    if isinstance(value, sympy.Interval):
        return sympy.sstr(value).replace("**", "^")
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, sympy.Expr):
        return render_expr(value)
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(display_sympy_value(item) for item in value) + ")"
    return str(value)


def compile_distractor_value(
    item: MathItemSpec,
    distractor: Distractor,
    params: Mapping[str, Fraction] | None = None,
) -> object:
    """Compile one distractor for display or comparison."""
    symbols = build_symbols(item.symbols)

    if distractor.value is not None:
        return compile_expr(distractor.value, symbols, params)
    if distractor.components:
        return sympy.Tuple(
            *[compile_expr(entry, symbols, params) for entry in distractor.components]
        )
    return sympy.FiniteSet(
        *[compile_expr(entry, symbols, params) for entry in distractor.items]
    )


__all__ = [
    "MathCompileError",
    "SampledDomain",
    "compile_distractor_value",
    "declared_domain_size",
    "display_sympy_value",
    "fraction_text",
    "iter_parameter_combinations",
    "parameter_combinations",
    "render_authored_expr",
    "render_authored_expr_latex",
    "render_expr",
    "render_goal_display",
    "render_goal_display_latex",
    "render_item_segments",
    "render_item_text",
    "render_item_text_latex",
    "render_matrix",
    "render_matrix_latex",
    "render_relation",
    "render_relation_latex",
    "render_relations",
    "render_relations_latex",
    "representative_item",
    "sample_parameter_combinations",
    "substitute_expr",
    "substitute_item",
]
