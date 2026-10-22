"""Check the current reference's rubric consistency and executable answers."""

import json
from collections import Counter
from pathlib import Path

import pytest

from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
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
    for question in QUESTIONS:
        ratings = question["dimensions"]
        assert set(ratings) == {
            "execution_burden",
            "changing_state",
            "conceptual_interaction",
        }
        assert set(ratings.values()) <= {"low", "moderate", "high"}
        events = question["trace_event_count"]
        burden = "low" if events <= 5 else "moderate" if events <= 20 else "high"
        assert ratings["execution_burden"] == burden, question["question_id"]
        expected = (
            "hard"
            if ratings["conceptual_interaction"] == "high"
            else "easy"
            if all(r == "low" for r in ratings.values())
            else "medium"
        )
        assert question["difficulty"] == expected, question["question_id"]


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q["question_id"])
def test_reference_answer_matches_bounded_execution(question):
    content = {key: question[key] for key in CodeDifficultyQuestion.model_fields}
    result = check_concrete_correctness(
        CodeDifficultyQuestion.model_validate(content),
        LocalPythonTool(),
        2,
    )
    assert result.status == "passed", result.findings
