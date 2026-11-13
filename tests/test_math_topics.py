"""Deterministic topic generators: registry, determinism and validation."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest
import sympy

from edcraft_validator.domains.math.ir.schema import Distractor, MathItemSpec
from edcraft_validator.domains.math.ir.solve import solve_item
from edcraft_validator.domains.math.topics import (
    DerivativeTopic,
    DeterminantTopic,
    LinearSystemTopic,
    PercentageTopic,
    QuadraticTopic,
    all_topics,
    get_topic,
    topic_ids,
    topics_by_stage,
)
from edcraft_validator.domains.math.validation.harness import validate_item

SEEDS = tuple(range(10))
EXPECTED_IDS = (
    "school.percentage",
    "school.quadratic",
    "school.linear_system",
    "university.derivative",
    "university.determinant",
)


def test_registry_order_stages_and_lookup() -> None:
    topics = all_topics()

    assert len(topics) == 5
    assert topic_ids() == EXPECTED_IDS
    assert [topic.stage for topic in topics] == [
        "school",
        "school",
        "school",
        "university",
        "university",
    ]
    assert [topic.topic_id for topic in topics_by_stage("school")] == list(
        EXPECTED_IDS[:3]
    )
    assert [topic.topic_id for topic in topics_by_stage("university")] == list(
        EXPECTED_IDS[3:]
    )
    for topic_id in EXPECTED_IDS:
        assert get_topic(topic_id).topic_id == topic_id


def test_unknown_topic_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_topic("school.unknown")


@pytest.mark.parametrize("topic_id", EXPECTED_IDS)
def test_generators_are_deterministic_and_valid(topic_id: str) -> None:
    topic = get_topic(topic_id)

    for seed in SEEDS:
        first = topic.generate(seed=seed)
        second = topic.generate(seed=seed)

        assert isinstance(first, MathItemSpec)
        assert first.model_dump() == second.model_dump()
        report = validate_item(first)
        assert report.report.status == "passed", (
            topic_id,
            seed,
            report.report.findings,
        )


def test_quadratic_has_distinct_roots_and_no_root_distractors() -> None:
    topic = QuadraticTopic()

    for seed in SEEDS:
        item = topic.generate(seed=seed)
        solved = solve_item(item).value
        assert isinstance(solved, sympy.FiniteSet)
        roots = sorted(int(root) for root in solved)

        assert len(roots) == 2
        assert roots[0] != roots[1]
        assert 0 not in roots
        assert 2 <= len(item.distractors) <= 3
        assert all(distractor.misconception for distractor in item.distractors)
        values = [_distractor_number(distractor) for distractor in item.distractors]
        assert len(values) == len(set(values))
        assert set(values).isdisjoint(roots)


def test_linear_system_has_a_unique_integer_two_tuple() -> None:
    topic = LinearSystemTopic()

    for seed in SEEDS:
        item = topic.generate(seed=seed)
        solved = solve_item(item).value
        assert isinstance(solved, sympy.FiniteSet)
        candidates = list(solved)

        assert len(candidates) == 1
        solution = candidates[0]
        assert isinstance(solution, sympy.Tuple)
        assert len(solution) == 2
        assert all(value.is_Integer for value in solution)
        assert item.answer is not None
        assert item.answer.kind == "tuple"
        assert item.answer.items == [str(value) for value in solution]


def test_determinant_distractors_differ_from_the_key() -> None:
    topic = DeterminantTopic()

    for seed in SEEDS:
        item = topic.generate(seed=seed)
        solved = solve_item(item).value
        assert isinstance(solved, sympy.Integer)
        key = int(solved)

        assert key != 0
        assert len(item.distractors) == 2
        values = [_distractor_number(distractor) for distractor in item.distractors]
        assert key not in values
        assert len(values) == len(set(values))
        assert all(distractor.misconception for distractor in item.distractors)


def test_percentage_answer_is_exact_and_in_range() -> None:
    topic = PercentageTopic()

    for seed in SEEDS:
        item = topic.generate(seed=seed)
        assert item.answer is not None
        assert item.answer.kind == "numeric"
        declared = Fraction(item.answer.items[0])

        solved = sympy.Rational(solve_item(item).value)
        exact = Fraction(int(solved.p), int(solved.q))

        assert declared == exact
        assert 0 < declared <= 200


def test_derivative_answer_is_an_expression_without_float_literals() -> None:
    topic = DerivativeTopic()

    for seed in SEEDS:
        item = topic.generate(seed=seed)
        solved = solve_item(item)

        assert solved.answer.kind == "expression"
        assert item.answer is not None
        assert item.answer.kind == "expression"
        payload = item.model_dump(mode="json")
        assert not _contains_float(payload)
        assert all(literal.lstrip("-").isdigit() for literal in _num_literals(payload))


def _distractor_number(distractor: Distractor) -> int:
    assert distractor.value is not None
    assert distractor.value.num is not None
    return int(distractor.value.num)


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_float(child) for child in value)
    return False


def _num_literals(value: Any) -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for key, child in value.items():
            if key == "num" and isinstance(child, str):
                found.append(child)
            else:
                found.extend(_num_literals(child))
        return found
    if isinstance(value, list):
        elements: list[str] = []
        for child in value:
            elements.extend(_num_literals(child))
        return elements
    return []
