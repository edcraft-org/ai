"""Frozen mathematics fixtures and the offline runner that checks them."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace

import pytest

from scripts import evaluate_math_fixtures as evaluation

FIXTURES = evaluation.load_fixtures()
FIXTURE_IDS = [fixture.id for fixture in FIXTURES]


@pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
def test_fixture_matches_its_expectation(fixture):
    result = evaluation.evaluate_fixture(fixture)

    assert result.actual == fixture.expected, result.findings
    if fixture.expected_code is not None:
        assert fixture.expected_code in result.codes, result.codes
    assert result.matched, result.mismatch_reasons

    if result.actual == "pass":
        assert result.determinism is not None
        assert result.determinism["identical"] is True
        assert result.determinism["no_external_calls"] is True
        assert result.determinism["external_calls"] == []
        assert result.determinism["error"] is None


def test_fixture_set_covers_the_declared_categories_and_goals():
    assert len(FIXTURES) >= 20
    counts = Counter(fixture.category for fixture in FIXTURES)
    assert counts["correct"] >= 6
    assert counts["incorrect"] >= 6
    assert counts["equivalent"] >= 4
    assert counts["unsupported"] >= 4
    assert len(set(FIXTURE_IDS)) == len(FIXTURES)
    assert all(fixture.schema_error is None for fixture in FIXTURES)

    templates = [fixture.template for fixture in FIXTURES if fixture.template]
    goals = {template.body.goal.kind for template in templates}
    assert {
        "solve",
        "expand",
        "factor",
        "simplify",
        "evaluate",
        "derivative",
        "integral",
        "determinant",
    } <= goals
    assert {"limit", "eigenvalues"} <= goals
    assert any(
        template.body.text.mode == "prose" and template.body.text.anchors
        for template in templates
    )
    assert any(
        template.body.answer_recipe is not None
        and template.body.answer_recipe.kind == "interval"
        for template in templates
    )


def test_summary_counts_outcomes_and_lists_every_mismatch(tmp_path):
    passing = next(fixture for fixture in FIXTURES if fixture.expected == "pass")
    rejecting = next(fixture for fixture in FIXTURES if fixture.expected == "reject")
    good = evaluation.evaluate_fixture(passing)
    bad = replace(
        evaluation.evaluate_fixture(rejecting),
        actual="pass",
        matched=False,
        mismatch_reasons=["expected reject, observed pass"],
    )

    output = tmp_path / "records.jsonl"
    summary = evaluation.write_results([good, bad], output)

    assert summary["fixture_count"] == 2
    assert summary["matched"] == 1
    assert summary["mismatched"] == 1
    assert summary["mismatches"] == [
        {
            "id": rejecting.id,
            "category": rejecting.category,
            "expected": rejecting.expected,
            "actual": "pass",
            "expected_code": rejecting.expected_code,
            "codes": bad.codes,
            "reasons": ["expected reject, observed pass"],
        }
    ]

    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [record["id"] for record in records] == [passing.id, rejecting.id]
    summary_path = tmp_path / "records.summary.json"
    assert json.loads(summary_path.read_text()) == summary


def test_main_returns_nonzero_when_a_fixture_mismatches(monkeypatch):
    monkeypatch.setattr(
        evaluation,
        "run",
        lambda fixtures_dir, output: {"mismatched": 1},
    )

    assert evaluation.main([]) == 1
