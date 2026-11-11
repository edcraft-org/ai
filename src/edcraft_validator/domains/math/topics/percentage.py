"""Deterministic percentage items with exact rational answers."""

from __future__ import annotations

import random
from fractions import Fraction

from edcraft_validator.domains.math.ir.schema import (
    Answer,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    PrimitiveSpec,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.topics.base import TopicGenerator, TopicStage
from edcraft_validator.domains.math.topics.nodes import div, mul, num

_PART_PERCENTS = (5, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 75, 80)
_PART_WHOLES = (20, 25, 40, 50, 60, 75, 80, 100, 120, 150, 200)
_WHOLE_PERCENTS = (5, 10, 20, 25, 50)
_WHOLES = (20, 40, 60, 80, 100, 120, 140, 160, 180, 200)


class PercentageTopic(TopicGenerator):
    """Find a percentage part, or recover the whole from a part and percent."""

    topic_id = "school.percentage"
    stage: TopicStage = "school"
    answer_primitive = "numeric"

    def generate(self, *, seed: int) -> MathItemSpec:
        rng = random.Random(seed)
        if rng.random() < 0.5:
            return self._part_of(rng)
        return self._whole_from_part(rng)

    def _part_of(self, rng: random.Random) -> MathItemSpec:
        percent = rng.choice(_PART_PERCENTS)
        whole = rng.choice(_PART_WHOLES)
        answer = Fraction(percent * whole, 100)
        expression = div(mul(num(percent), num(whole)), num(100))
        text = f"Find {percent}% of {whole}."
        return _build_item(
            expression=expression,
            answer_text=_render_fraction(answer),
            text=text,
            values=[str(percent), str(whole)],
        )

    def _whole_from_part(self, rng: random.Random) -> MathItemSpec:
        percent = rng.choice(_WHOLE_PERCENTS)
        whole = rng.choice(_WHOLES)
        part = percent * whole // 100
        expression = div(mul(num(part), num(100)), num(percent))
        text = f"{part} is {percent}% of what number?"
        return _build_item(
            expression=expression,
            answer_text=str(whole),
            text=text,
            values=[str(part), str(percent)],
        )


def _build_item(
    *,
    expression: Expr,
    answer_text: str,
    text: str,
    values: list[str],
) -> MathItemSpec:
    return MathItemSpec(
        topic="school.percentage",
        symbols=[SymbolSpec(name="amount", kind="given", domain="rational")],
        givens=[Given(id="data", kind="dataset", values=values)],
        goal=Goal(kind="evaluate", expr=expression),
        answer=Answer(kind="numeric", items=[answer_text], display=answer_text),
        text=TextSpec(mode="symbolic", template=text),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
    )


def _render_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"
