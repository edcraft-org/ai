"""Deterministic 2x2 linear systems with unique integer solutions."""

from __future__ import annotations

import random

from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Given,
    Goal,
    MathItemSpec,
    PrimitiveSpec,
    Relation,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.topics.base import TopicGenerator, TopicStage
from edcraft_validator.domains.math.topics.nodes import add, mul, num, sym

_COEFFICIENTS = tuple(range(-4, 5))
_SOLUTION_RANGE = range(-4, 5)
_MAX_ATTEMPTS = 64


class LinearSystemTopic(TopicGenerator):
    """A 2x2 integer system with one unique integer solution."""

    topic_id = "school.linear_system"
    stage: TopicStage = "school"
    # The solver returns a finite set holding one tuple. ``collection`` cannot
    # compare a single tuple element, so the tuple answer uses solution_set.
    answer_primitive = "solution_set"

    def generate(self, *, seed: int) -> MathItemSpec:
        rng = random.Random(seed)
        solution_x = rng.choice(tuple(_SOLUTION_RANGE))
        solution_y = rng.choice(tuple(_SOLUTION_RANGE))
        a, b, c, d = _coefficients(rng)
        rhs_first = a * solution_x + b * solution_y
        rhs_second = c * solution_x + d * solution_y
        first = Relation(
            kind="eq",
            lhs=add(mul(num(a), sym("x")), mul(num(b), sym("y"))),
            rhs=num(rhs_first),
        )
        second = Relation(
            kind="eq",
            lhs=add(mul(num(c), sym("x")), mul(num(d), sym("y"))),
            rhs=num(rhs_second),
        )
        text = (
            f"Solve the system {_linear_side(a, b)} = {rhs_first} "
            f"and {_linear_side(c, d)} = {rhs_second}."
        )
        return MathItemSpec(
            topic="school.linear_system",
            symbols=[
                SymbolSpec(name="x", domain="real"),
                SymbolSpec(name="y", domain="real"),
            ],
            givens=[
                Given(id="eq1", relation=first),
                Given(id="eq2", relation=second),
            ],
            goal=Goal(kind="solve", symbols=["x", "y"], domain="real"),
            answer=Answer(
                kind="tuple",
                items=[str(solution_x), str(solution_y)],
                display=f"({solution_x}, {solution_y})",
            ),
            text=TextSpec(mode="symbolic", template=text),
            validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
        )


def _coefficients(rng: random.Random) -> tuple[int, int, int, int]:
    a = b = c = d = 0
    for _ in range(_MAX_ATTEMPTS):
        a = rng.choice(_COEFFICIENTS)
        b = rng.choice(_COEFFICIENTS)
        c = rng.choice(_COEFFICIENTS)
        d = rng.choice(_COEFFICIENTS)
        if a == 0 and b == 0:
            continue
        if c == 0 and d == 0:
            continue
        if a * d - b * c == 0:
            continue
        return a, b, c, d
    return 2, 1, 1, 1


def _linear_side(a: int, b: int) -> str:
    rendered = ""
    for coefficient, variable in ((a, "x"), (b, "y")):
        if coefficient == 0:
            continue
        if not rendered:
            rendered = _signed_term(coefficient, variable)
        else:
            sign = "+" if coefficient > 0 else "-"
            rendered += f" {sign} {_positive_term(abs(coefficient), variable)}"
    return rendered


def _signed_term(coefficient: int, variable: str) -> str:
    if coefficient < 0:
        return "-" + _positive_term(-coefficient, variable)
    return _positive_term(coefficient, variable)


def _positive_term(coefficient: int, variable: str) -> str:
    if coefficient == 1:
        return variable
    return f"{coefficient}{variable}"
