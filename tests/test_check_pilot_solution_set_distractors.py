"""Supported option counts also work for empty and all-real solution sets."""

import random

import pytest

from edcraft_validator.application.check_pilot.solution_sets import (
    render_solution_set,
    sets_equal,
    solution_set_mutations,
    solve_relation_independently,
)


@pytest.mark.parametrize(
    ("relation", "coefficients"),
    [
        ("lt", (1, 0, 1)),
        ("ge", (1, 0, 1)),
        ("ge", (-12, -12, -12)),
        ("le", (-12, -12, -12)),
    ],
)
def test_five_distinct_wrong_options_for_empty_and_all_real_answers(
    relation, coefficients
):
    expected = solve_relation_independently(relation, coefficients)

    wrong = solution_set_mutations(
        relation, coefficients, expected, 5, rng=random.Random(42)
    )

    assert len(wrong) == 5
    assert len({render_solution_set(candidate) for candidate in wrong}) == 5
    assert all(not sets_equal(expected, candidate) for candidate in wrong)
    replay = solution_set_mutations(
        relation, coefficients, expected, 5, rng=random.Random(42)
    )
    assert [render_solution_set(candidate) for candidate in replay] == [
        render_solution_set(candidate) for candidate in wrong
    ]
