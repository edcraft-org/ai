"""Deterministic polynomial differentiation items."""

from __future__ import annotations

import random

from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Distractor,
    Given,
    Goal,
    MathItemSpec,
    PrimitiveSpec,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.topics.base import TopicGenerator, TopicStage
from edcraft_validator.domains.math.topics.nodes import add, mul, num, power, sym

_NONZERO_COEFFICIENTS = (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)
_COEFFICIENTS = tuple(range(-5, 6))


class DerivativeTopic(TopicGenerator):
    """Differentiate ``a*x^n + b*x + c`` with the power rule."""

    topic_id = "university.derivative"
    stage: TopicStage = "university"
    answer_primitive = "expression_equiv"

    def generate(self, *, seed: int) -> MathItemSpec:
        rng = random.Random(seed)
        exponent = rng.randint(2, 5)
        leading = rng.choice(_NONZERO_COEFFICIENTS)
        linear = rng.choice(_COEFFICIENTS)
        constant = rng.choice(_COEFFICIENTS)
        expression = add(
            mul(num(leading), power(sym("x"), num(exponent))),
            mul(num(linear), sym("x")),
            num(constant),
        )
        polynomial = _join_terms(
            [(leading, exponent), (linear, 1), (constant, 0)],
            expression=False,
        )
        derivative = _join_terms(
            [(leading * exponent, exponent - 1), (linear, 0)],
            expression=True,
        )
        slip = add(
            mul(num(leading), power(sym("x"), num(exponent - 1))),
            num(linear),
        )
        return MathItemSpec(
            topic="university.derivative",
            symbols=[SymbolSpec(name="x", domain="real")],
            givens=[Given(id="domain_x", kind="domain", symbol="x", domain="real")],
            goal=Goal(kind="derivative", symbol="x", expr=expression, order=1),
            answer=Answer(
                kind="expression",
                items=[derivative],
                display=derivative,
            ),
            distractors=[
                Distractor(
                    value=slip,
                    misconception="POWER_RULE_MISSING_COEFFICIENT",
                    reason="Forgets to multiply by the original exponent",
                )
            ],
            text=TextSpec(
                mode="symbolic",
                template=f"Differentiate {polynomial} with respect to x.",
            ),
            validation=ValidationSpec(
                primitives=[PrimitiveSpec(type="expression_equiv")]
            ),
        )


def _join_terms(terms: list[tuple[int, int]], *, expression: bool) -> str:
    rendered = ""
    for coefficient, exponent in terms:
        if coefficient == 0:
            continue
        if not rendered:
            rendered = _signed_term(coefficient, exponent, expression)
        else:
            sign = "+" if coefficient > 0 else "-"
            rendered += f" {sign} {_term(abs(coefficient), exponent, expression)}"
    return rendered or "0"


def _signed_term(coefficient: int, exponent: int, expression: bool) -> str:
    if coefficient < 0:
        return "-" + _term(-coefficient, exponent, expression)
    return _term(coefficient, exponent, expression)


def _term(coefficient: int, exponent: int, expression: bool) -> str:
    if exponent == 0:
        return str(coefficient)
    if expression:
        base = "x" if exponent == 1 else f"x**{exponent}"
        if coefficient == 1:
            return base
        return f"{coefficient}*{base}"
    base = "x" if exponent == 1 else f"x^{exponent}"
    if coefficient == 1:
        return base
    return f"{coefficient}{base}"
