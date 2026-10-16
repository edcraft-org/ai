"""Compare one independently selected difficulty with the authoring target."""

from typing import Literal

from edcraft_validator.domains.code.code_types import Difficulty

DifficultyMatch = Literal["matches", "too_easy", "too_hard"]


def compare_difficulty(estimated: Difficulty, requested: Difficulty) -> DifficultyMatch:
    order = {"easy": 0, "medium": 1, "hard": 2}

    delta = order[estimated] - order[requested]
    return "matches" if delta == 0 else "too_easy" if delta < 0 else "too_hard"
