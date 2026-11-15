"""Check the current reference's rubric consistency and executable answers."""

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from judge_helpers import question

from edcraft_validator.application.difficulty_rubrics import (
    difficulty_rubric,
    register_difficulty_rubric,
)
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    load_code_difficulty_rubric,
)
from edcraft_validator.domains.code.question_checks import check_concrete_correctness
from edcraft_validator.tools.python_execution import LocalPythonTool

DATASET = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "reference_sets/python_tracing/dataset.json"
    ).read_text()
)
QUESTIONS = DATASET["questions"]


def test_current_reference_ratings_follow_v03_boundaries():
    assert DATASET["rubric_version"] == "python-tracing-v0.3"
    assert len({q["question_id"] for q in QUESTIONS}) == 30
    assert Counter(q["difficulty"] for q in QUESTIONS) == {
        "easy": 15,
        "medium": 9,
        "hard": 6,
    }

    for item in QUESTIONS:
        ratings = item["dimensions"]
        assert set(ratings) == {
            "execution_burden",
            "changing_state",
            "conceptual_interaction",
        }
        assert set(ratings.values()) <= {"low", "moderate", "high"}
        events = item["trace_event_count"]
        burden = "low" if events <= 5 else "moderate" if events <= 20 else "high"
        assert ratings["execution_burden"] == burden, item["question_id"]
        expected = (
            "hard"
            if ratings["conceptual_interaction"] == "high"
            else "easy"
            if all(r == "low" for r in ratings.values())
            else "medium"
        )
        assert item["difficulty"] == expected, item["question_id"]


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q["question_id"])
def test_reference_answer_matches_bounded_execution(question):
    content = {key: question[key] for key in CodeDifficultyQuestion.model_fields}

    result = check_concrete_correctness(
        CodeDifficultyQuestion.model_validate(content),
        LocalPythonTool(),
        2,
    )
    assert result.status == "passed", result.findings


def test_packaged_rubric_resource_matches_source(monkeypatch, tmp_path):
    from edcraft_validator.application import difficulty_rubrics

    resource = tmp_path / "difficulty-rubric.md"
    resource.write_bytes(Path("docs/difficulty-rubric.md").read_bytes())
    monkeypatch.setattr(difficulty_rubrics, "files", lambda package: tmp_path)

    assert (
        load_code_difficulty_rubric().sha256
        == hashlib.sha256(resource.read_bytes()).hexdigest()
    )


def test_registering_the_same_rubric_twice_is_idempotent():
    rubric = load_code_difficulty_rubric()

    register_difficulty_rubric(rubric)
    register_difficulty_rubric(rubric)

    assert difficulty_rubric(rubric.rubric_id) == rubric


def test_registering_a_different_rubric_for_a_taken_id_is_rejected():
    rubric = load_code_difficulty_rubric()

    with pytest.raises(ValueError, match="different difficulty rubric"):
        register_difficulty_rubric(replace(rubric, version="other"))


def test_rubric_lookup_loads_a_domain_rubric_on_demand(monkeypatch):
    from edcraft_validator.application import difficulty_rubrics

    monkeypatch.setattr(difficulty_rubrics, "_RUBRICS", {})

    assert difficulty_rubric("math").rubric_id == "math"


def test_question_revision_changes_identity():
    original = question()
    edited = original.model_copy(update={"question": "Return value of f(3)?"})
    assert original.sha256 != edited.sha256
