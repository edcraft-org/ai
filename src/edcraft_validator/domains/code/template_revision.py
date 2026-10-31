"""Shared code difficulty definitions supplied to authors."""

from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric


def author_difficulty_guidance() -> str:
    rubric = load_code_difficulty_rubric()
    levels = (
        rubric.text.split("| Level | Anchor description |", 1)[1]
        .split("Choose the closest worked anchor", 1)[0]
        .strip()
    )
    return (
        "Difficulty definitions shared with the checker, without worked examples:\n"
        "| Level | Anchor description |\n" + levels + "\n"
        "Apply these to the typical instance across independent, uniformly chosen "
        "parameter values, under manual untimed tracing with scratch paper. "
        "Consider execution burden, changing state, conceptual interaction and "
        "answer discrimination together. Account for shortcuts and irrelevant code. "
        "Extra syntax or larger loop bounds alone do not establish hard difficulty."
    )
