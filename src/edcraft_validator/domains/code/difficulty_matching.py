"""One uncertainty-aware comparison rule for human and model assessments."""

from typing import Literal

from edcraft_validator.domains.code.code_types import Difficulty

DifficultyMatch = Literal["matches", "too_easy", "too_hard", "uncertain"]


def compare_difficulty(
    estimated: Difficulty | None,
    requested: Difficulty,
    confidence: str,
    alternatives: list[Difficulty],
) -> DifficultyMatch:
    if estimated is None or confidence == "low":
        return "uncertain"
    order = {"easy": 0, "medium": 1, "hard": 2}

    def compare(level: Difficulty) -> DifficultyMatch:
        delta = order[level] - order[requested]
        return "matches" if delta == 0 else "too_easy" if delta < 0 else "too_hard"

    decision = compare(estimated)
    if any(compare(level) != decision for level in alternatives):
        return "uncertain"
    return decision
