"""Deterministic monic quadratic items with integer roots."""

from __future__ import annotations

import random

from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Distractor,
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
from edcraft_validator.domains.math.topics.nodes import add, mul, num, power, sym

_ROOT_RANGE = tuple(r for r in range(-6, 7) if r != 0)


class QuadraticTopic(TopicGenerator):
    """Solve ``x^2 - (r1 + r2)x + r1*r2 = 0`` for distinct integer roots."""

    topic_id = "school.quadratic"
    stage: TopicStage = "school"
    answer_primitive = "solution_set"

    def generate(self, *, seed: int) -> MathItemSpec:
        rng = random.Random(seed)
        first = rng.choice(_ROOT_RANGE)
        second = rng.choice(
            [root for root in _ROOT_RANGE if root != first and root != -first]
        )
        linear = -(first + second)
        constant = first * second
        lhs = add(
            power(sym("x"), num(2)),
            mul(num(linear), sym("x")),
            num(constant),
        )
        roots = sorted((first, second))
        items = [str(root) for root in roots]
        return MathItemSpec(
            topic="school.quadratic",
            symbols=[SymbolSpec(name="x", domain="real")],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(kind="eq", lhs=lhs, rhs=num(0)),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            answer=Answer(
                kind="set",
                items=items,
                display="{" + ", ".join(items) + "}",
            ),
            distractors=_distractors(first, second),
            text=TextSpec(
                mode="symbolic",
                template=f"Solve {_quadratic_text(linear, constant)}.",
            ),
            validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
        )


def _quadratic_text(linear: int, constant: int) -> str:
    parts = ["x^2"]
    if linear:
        term = "x" if abs(linear) == 1 else f"{abs(linear)}x"
        parts.append(("+ " if linear > 0 else "- ") + term)
    if constant:
        parts.append(("+ " if constant > 0 else "- ") + str(abs(constant)))
    return " ".join(parts) + " = 0"


def _distractors(first: int, second: int) -> list[Distractor]:
    options = [
        (-first, "SIGN_ERROR", "Flips the sign of one root"),
        (-second, "SIGN_ERROR", "Flips the sign of the other root"),
        (first + second, "SUM_AS_ROOT", "Reports the root sum as a root"),
        (first * second, "PRODUCT_AS_ROOT", "Reports the root product as a root"),
        (second - first, "ARITHMETIC_SLIP", "Subtracts the roots in reverse"),
        (first - second, "SIGN_ERROR", "Subtracts the roots in reverse"),
        (first + 1, "ARITHMETIC_SLIP", "Adds one to a root"),
        (second - 1, "ARITHMETIC_SLIP", "Subtracts one from a root"),
    ]
    roots = {first, second}
    seen: set[int] = set()
    distractors: list[Distractor] = []
    for value, misconception, reason in options:
        if value in roots or value in seen:
            continue
        seen.add(value)
        distractors.append(
            Distractor(
                value=num(value),
                misconception=misconception,
                reason=reason,
            )
        )
        if len(distractors) == 3:
            break
    return distractors
