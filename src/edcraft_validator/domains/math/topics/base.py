"""Shared contract for deterministic math topic generators.

A topic is a generator, not a validator. It emits a typed ``MathItemSpec`` and
leaves solving, rendering and validation to the shared engine.
"""

from __future__ import annotations

from typing import Literal, Protocol

from edcraft_validator.domains.math.ir.schema import MathItemSpec

TopicStage = Literal["school", "university"]


class TopicGenerator(Protocol):
    """One deterministic item family keyed by a stable topic id."""

    topic_id: str
    stage: TopicStage
    answer_primitive: str

    def generate(self, *, seed: int) -> MathItemSpec:
        """Return one concrete spec. The same seed must yield the same spec."""
        ...
