"""Domain-neutral property checking: sampling, budgets and coverage."""

from fractions import Fraction

import pytest

from edcraft_validator.validation.property_checks import (
    PropertyCheckRun,
    PropertyCheckSettings,
)
from edcraft_validator.validation.validation_contracts import ValidationFailure


def record_run(parameters, boundary, *, settings=None, cover_small_domain=False):
    record = []
    run = PropertyCheckRun(settings or PropertyCheckSettings())

    def property_check(inputs, budget):
        record.append(inputs)
        return inputs

    result = run.check(
        parameters, boundary, property_check, cover_small_domain=cover_small_domain
    )
    return run, record, result


def test_same_seed_replays_the_same_inputs():
    parameters = {"n": list(range(20)), "m": list(range(5))}

    _, first, _ = record_run(
        parameters, [], settings=PropertyCheckSettings(max_examples=8, seed=7)
    )
    _, second, _ = record_run(
        parameters, [], settings=PropertyCheckSettings(max_examples=8, seed=7)
    )

    assert first == second
    assert 1 <= len(first) <= 8


def test_boundary_examples_are_checked_before_generated_inputs():
    parameters = {"n": list(range(100))}
    boundary = [{"n": 0}, {"n": 99}, {"n": 50}]

    _, record, _ = record_run(
        parameters, boundary, settings=PropertyCheckSettings(max_examples=3)
    )

    assert record[: len(boundary)] == boundary
    assert record[len(boundary) :]  # the generate phase still ran


def test_budget_exhaustion_raises_the_budget_error():
    run = PropertyCheckRun(PropertyCheckSettings(max_execution_calls=2))

    def property_check(inputs, budget):
        budget.reserve_execution()
        return inputs

    with pytest.raises(ValidationFailure) as exc:
        run.check({"n": list(range(100))}, [], property_check)

    assert exc.value.code == "PROPERTY_CHECK_BUDGET_EXCEEDED"
    assert exc.value.context["execution_calls"] == run.execution_calls == 2
    assert exc.value.context["whole_domain"] is False


def test_small_domain_is_checked_exhaustively_once():
    parameters = {"a": [0, 1], "b": ["x", "y", "z"]}
    run, record, _ = record_run(
        parameters,
        [{"a": 0, "b": "x"}],
        cover_small_domain=True,
    )

    expected = [(a, b) for a in parameters["a"] for b in parameters["b"]]
    assert [(item["a"], item["b"]) for item in record] == expected
    assert run.whole_domain is True
    assert run.details()["whole_domain"] is True
    assert run.details()["examples_checked"] == len(expected)


def test_domain_above_the_sample_budget_is_not_claimed_as_whole():
    run, _, _ = record_run(
        {"a": [0, 1, 2], "b": [0, 1, 2]},
        [],
        settings=PropertyCheckSettings(max_examples=5),
        cover_small_domain=True,
    )

    assert run.whole_domain is False
    assert run.details()["whole_domain"] is False


def test_default_details_report_no_whole_domain_coverage():
    run, _, _ = record_run({"a": [0, 1]}, [{"a": 0}])

    assert run.details()["whole_domain"] is False


def test_fraction_values_are_sampled_and_deduplicated():
    parameters = {"p": [Fraction(1, 3), Fraction(2, 3)]}
    run, record, _ = record_run(
        parameters,
        [{"p": Fraction(2, 3)}],
        cover_small_domain=True,
    )

    assert record == [{"p": Fraction(2, 3)}, {"p": Fraction(1, 3)}]
    assert run.whole_domain is True
    assert run.details()["examples_checked"] == 2
