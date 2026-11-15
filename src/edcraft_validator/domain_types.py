"""Vocabulary shared by authoring domains.

These values are wire vocabulary, not domain logic. Keeping one definition stops
the math and code domains from drifting apart on difficulty labels or the
authoring control ranges.
"""

from __future__ import annotations

from typing import Literal, get_args

Difficulty = Literal["easy", "medium", "hard"]

DIFFICULTIES: tuple[Difficulty, ...] = get_args(Difficulty)

# Shared authoring controls. Domains may add narrower concrete-item ranges.
MIN_DISTRACTORS = 1
DEFAULT_DISTRACTORS = 3
MAX_DISTRACTORS = 10
MAX_DISTRACTOR_CANDIDATES = 12
MIN_CHOICES = MIN_DISTRACTORS + 1
MAX_CHOICES = MAX_DISTRACTORS + 1
