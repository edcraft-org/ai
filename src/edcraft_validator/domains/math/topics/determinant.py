"""Deterministic 2x2 determinant items."""

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
from edcraft_validator.domains.math.topics.nodes import num

_ENTRIES = (-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6)
_MAX_ATTEMPTS = 64


class DeterminantTopic(TopicGenerator):
    """Find the determinant of a 2x2 integer matrix with a nonzero key."""

    topic_id = "university.determinant"
    stage: TopicStage = "university"
    answer_primitive = "numeric"

    def generate(self, *, seed: int) -> MathItemSpec:
        rng = random.Random(seed)
        a, b, c, d = _entries(rng)
        determinant = a * d - b * c
        text = f"Find the determinant of [[{a}, {b}], [{c}, {d}]]."
        return MathItemSpec(
            topic="university.determinant",
            symbols=[SymbolSpec(name="m", kind="given", domain="integer")],
            givens=[
                Given(
                    id="entries",
                    kind="dataset",
                    values=[str(a), str(b), str(c), str(d)],
                )
            ],
            goal=Goal(
                kind="determinant",
                matrix=[[num(a), num(b)], [num(c), num(d)]],
            ),
            answer=Answer(
                kind="numeric",
                items=[str(determinant)],
                display=str(determinant),
            ),
            distractors=_distractors(a, b, c, d, determinant),
            text=TextSpec(mode="symbolic", template=text),
            validation=ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
        )


def _entries(rng: random.Random) -> tuple[int, int, int, int]:
    a = b = c = d = 0
    for _ in range(_MAX_ATTEMPTS):
        a = rng.choice(_ENTRIES)
        b = rng.choice(_ENTRIES)
        c = rng.choice(_ENTRIES)
        d = rng.choice(_ENTRIES)
        if a * d - b * c != 0:
            return a, b, c, d
    return 1, 2, 3, 4


def _distractors(
    a: int,
    b: int,
    c: int,
    d: int,
    determinant: int,
) -> list[Distractor]:
    options = [
        (a * d + b * c, "SIGN_ERROR", "Adds the cross term instead of subtracting"),
        (a * b - c * d, "MINOR_SWAP", "Swaps the diagonal pairings"),
        (a * d, "MISSING_MINOR", "Keeps only the main diagonal product"),
    ]
    seen: set[int] = set()
    distractors: list[Distractor] = []
    for value, misconception, reason in options:
        if value == determinant or value in seen:
            continue
        seen.add(value)
        distractors.append(
            Distractor(
                value=num(value),
                misconception=misconception,
                reason=reason,
            )
        )
        if len(distractors) == 2:
            break
    return distractors
