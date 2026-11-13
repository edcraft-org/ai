"""Goal-form registry for authored answer recipes.

Form is deliberately separate from correctness: the deterministic engine decides
whether an answer is mathematically right, while this registry decides whether
it has the shape the goal's notation demands -- a fully expanded polynomial, a
product of irreducible factors, a solution set, a finite scalar determinant,
and so on.

Every check is total: :func:`check_form` returns a :class:`FormResult` and
never raises. SymPy is used only here; the registry inspects the compiled
answer, never the goal, so notation and truth stay independent verdicts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

import sympy

from edcraft_validator.domains.math.ir.compile import build_symbols
from edcraft_validator.domains.math.ir.schema import AnswerRecipe, MathItemSpec
from edcraft_validator.domains.math.validation.answers import compile_answer_recipe

FormStatus = Literal["pass", "fail", "unsupported"]

_EXPRESSION_ANSWER_KINDS = frozenset({"numeric", "expression"})
_SET_TUPLE_ANSWER_KINDS = frozenset({"set", "tuple"})


@dataclass(frozen=True)
class FormResult:
    status: FormStatus
    reason: str = ""


FormRule = Callable[
    [MathItemSpec, AnswerRecipe, Mapping[str, Fraction] | None],
    FormResult,
]


def check_form(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None = None,
) -> FormResult:
    """Check the answer's form for the item's goal; total, never raises."""
    if answer.kind in {"interval", "boolean"}:
        return FormResult("unsupported", f"no form rule for {answer.kind} answers")
    rule = _FORM_RULES.get(item.goal.kind)
    if rule is None:
        return FormResult("unsupported", f"no form rule for {item.goal.kind!r} goals")
    return rule(item, answer, params)


# ---------------------------------------------------------------------------
# Shared helpers


def _compile_answer(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
) -> tuple[object, None] | tuple[None, FormResult]:
    """Compile the recipe; any refusal becomes a ``fail`` result, never a raise."""
    try:
        return compile_answer_recipe(answer, item.symbols, params), None
    except Exception as exc:  # total: an uncompilable answer has the wrong form
        return None, FormResult("fail", f"answer does not compile: {exc}")


def _single_expression(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
    goal: str,
    *,
    non_expression: FormStatus,
) -> tuple[sympy.Expr, None] | tuple[None, FormResult]:
    """Require one compiled expression answer; non-expression kinds are refused."""
    if answer.kind not in _EXPRESSION_ANSWER_KINDS:
        return None, FormResult(
            non_expression, f"{goal} form applies to expression answers only"
        )
    compiled, failure = _compile_answer(item, answer, params)
    if failure is not None:
        return None, failure
    if not isinstance(compiled, sympy.Expr):
        return None, FormResult("fail", f"{goal} answers must be a single expression")
    return compiled, None


def _declared_poly(
    expr: sympy.Expr,
    item: MathItemSpec,
) -> tuple[sympy.Poly, None] | tuple[None, FormResult]:
    """Return the polynomial over the item's declared symbols, or a failure."""
    declared = list(build_symbols(item.symbols).values())
    undeclared = sorted(str(symbol) for symbol in expr.free_symbols - set(declared))
    if undeclared:
        return None, FormResult(
            "fail", "answer uses undeclared symbols: " + ", ".join(undeclared)
        )
    try:
        return sympy.Poly(expr, *declared), None
    except Exception as exc:  # total: non-polynomial answers fail, never raise
        return None, FormResult(
            "fail", f"answer is not a polynomial in the declared symbols: {exc}"
        )


def _has_unexpanded_sum_power(expr: sympy.Expr) -> bool:
    """Whether some integer power of a sum still waits to be multiplied out."""
    for power in expr.atoms(sympy.Pow):
        exponent = power.exp
        if power.base.is_Add and exponent.is_Integer and exponent >= 2:
            return True
    return False


def _factor_bases(expr: sympy.Expr) -> list[sympy.Expr]:
    """Split a factored expression into its multiplicative bases."""
    bases: list[sympy.Expr] = []
    for factor in sympy.Mul.make_args(expr):
        if isinstance(factor, sympy.Pow) and factor.exp.is_Integer and factor.exp >= 1:
            bases.append(factor.base)
        else:
            bases.append(factor)
    return bases


# ---------------------------------------------------------------------------
# Per-goal form rules


def _expanded_form(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
) -> FormResult:
    compiled, failure = _single_expression(
        item, answer, params, "expand", non_expression="fail"
    )
    if failure is not None:
        return failure
    _poly, failure = _declared_poly(compiled, item)
    if failure is not None:
        return failure
    if sympy.expand(compiled) != compiled:
        return FormResult("fail", "answer is not fully expanded")
    if _has_unexpanded_sum_power(compiled):
        return FormResult("fail", "answer contains an unexpanded power of a sum")
    return FormResult("pass")


def _factored_form(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
) -> FormResult:
    compiled, failure = _single_expression(
        item, answer, params, "factor", non_expression="fail"
    )
    if failure is not None:
        return failure
    poly, failure = _declared_poly(compiled, item)
    if failure is not None:
        return failure
    if sympy.factor(compiled) != compiled:
        return FormResult("fail", "answer is not factored")
    for base in _factor_bases(compiled):
        try:
            base_poly = sympy.Poly(base, *poly.gens)
        except Exception as exc:  # total: a non-polynomial factor fails
            return FormResult("fail", f"factor {base} is not a polynomial: {exc}")
        if base_poly.total_degree() >= 2 and base_poly.is_irreducible is not True:
            return FormResult("fail", f"factor {base} is reducible")
    return FormResult("pass")


def _derivative_free_form(
    unevaluated: type[sympy.Basic],
    description: str,
) -> FormRule:
    """Build the calculus form rule: a plain expression without the operator."""

    def rule(
        item: MathItemSpec,
        answer: AnswerRecipe,
        params: Mapping[str, Fraction] | None,
    ) -> FormResult:
        compiled, failure = _single_expression(
            item,
            answer,
            params,
            item.goal.kind,
            non_expression="unsupported",
        )
        if failure is not None:
            return failure
        if compiled.has(unevaluated):
            return FormResult("fail", f"answer contains an unevaluated {description}")
        return FormResult("pass")

    return rule


def _solution_set_form(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
) -> FormResult:
    _compiled, failure = _compile_answer(item, answer, params)
    if failure is not None:
        return failure
    if answer.kind not in _SET_TUPLE_ANSWER_KINDS:
        return FormResult("fail", "solve answers must be a set or an ordered tuple")
    return FormResult("pass")


def _determinant_form(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
) -> FormResult:
    compiled, failure = _single_expression(
        item, answer, params, "determinant", non_expression="fail"
    )
    if failure is not None:
        return failure
    if not compiled.is_number:
        return FormResult("fail", "determinant answers must be a numeric scalar")
    if compiled.is_finite is not True:
        return FormResult("fail", "determinant answers must be finite")
    return FormResult("pass")


def _expression_form(
    item: MathItemSpec,
    answer: AnswerRecipe,
    params: Mapping[str, Fraction] | None,
) -> FormResult:
    _compiled, failure = _single_expression(
        item, answer, params, item.goal.kind, non_expression="fail"
    )
    if failure is not None:
        return failure
    return FormResult("pass")


_FORM_RULES: dict[str, FormRule] = {
    "evaluate": _expression_form,
    "simplify": _expression_form,
    "expand": _expanded_form,
    "factor": _factored_form,
    "derivative": _derivative_free_form(sympy.Derivative, "derivative"),
    "integral": _derivative_free_form(sympy.Integral, "integral"),
    "solve": _solution_set_form,
    "determinant": _determinant_form,
    # "limit" and "eigenvalues" have no entry: the registry reports them as
    # unsupported rather than inventing a form rule.
}
