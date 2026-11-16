"""Check the mathematics template difficulty reference set and its builder."""

import json
from collections import Counter
from pathlib import Path

from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from scripts import build_math_reference_set as builder

DATASET = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "reference_sets/math_templates/dataset.json"
    ).read_text()
)
QUESTIONS = DATASET["questions"]
ITEMS = builder.all_items()
LEVELS = {"low", "moderate", "high"}
REQUIRED_GOALS = {
    "evaluate",
    "solve",
    "simplify",
    "factor",
    "expand",
    "derivative",
    "integral",
    "determinant",
}


def test_dataset_shape_is_complete():
    assert DATASET["rubric_version"] == "math-ir-v0.1"
    assert len(QUESTIONS) == 60
    assert len({question["question_id"] for question in QUESTIONS}) == 60
    assert len({question["family"] for question in QUESTIONS}) >= 20
    assert REQUIRED_GOALS <= {question["goal_kind"] for question in QUESTIONS}

    for question in QUESTIONS:
        assert question["question_id"].startswith(f"{question['family']}-")
        assert question["question_id"].rsplit("-", 1)[-1].isdigit()
        assert question["split"] in {"development", "held_out"}
        template = MathTemplateSpec.model_validate(question["template"])
        assert len(template.body.distractors) == 3
        assert question["proposed_difficulty"] in {"easy", "medium", "hard"}
        assert set(question["proposed_dimensions"]) == {
            "procedure_length",
            "operation_type",
            "conceptual_demand",
            "answer_discrimination",
        }
        assert set(question["proposed_dimensions"].values()) <= LEVELS
        assert question["proposed_reason"]
        assert question["owner_difficulty"] is None
        assert question["owner_dimensions"] is None
        assert question["owner_notes"] is None
        assert len(question["instance"]["options"]) == 4
        assert question["instance"]["correct_option"] in {"A", "B", "C", "D"}


def test_level_counts_and_splits_are_balanced():
    levels = Counter(question["proposed_difficulty"] for question in QUESTIONS)
    assert set(levels) == {"easy", "medium", "hard"}
    assert all(15 <= count <= 25 for count in levels.values()), levels

    splits = Counter(question["split"] for question in QUESTIONS)
    assert splits == {"development": 42, "held_out": 18}

    family_splits = {}
    for question in QUESTIONS:
        family_splits.setdefault(question["family"], set()).add(question["split"])
    assert all(len(values) == 1 for values in family_splits.values())

    for split in {"development", "held_out"}:
        covered = {
            question["proposed_difficulty"]
            for question in QUESTIONS
            if question["split"] == split
        }
        assert covered == {"easy", "medium", "hard"}


def test_every_template_passes_production_checks():
    failures = {
        entry.question_id: problems
        for entry in ITEMS
        if (problems := builder.check_template(entry))
    }
    assert failures == {}


def test_stored_instances_match_a_fresh_seed_zero_render():
    for entry, stored in zip(ITEMS, QUESTIONS, strict=True):
        assert entry.question_id == stored["question_id"]
        assert builder.seed_zero_instance(entry) == stored["instance"]


def test_owner_fields_are_preserved_by_question_id(monkeypatch, tmp_path):
    previous = {
        "questions": [
            {
                "question_id": "arithmetic-evaluate-01",
                "owner_difficulty": "easy",
                "owner_dimensions": {"procedure_length": "low"},
                "owner_notes": "Reviewed in the paper pilot.",
            }
        ]
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(previous))
    monkeypatch.setattr(builder, "DATASET_PATH", path)
    monkeypatch.setattr(
        builder,
        "seed_zero_instance",
        lambda entry: {"question": "", "options": [], "correct_option": "A"},
    )

    dataset = builder.build_dataset(ITEMS)
    owned = dataset["questions"][0]
    assert owned["question_id"] == "arithmetic-evaluate-01"
    assert owned["owner_difficulty"] == "easy"
    assert owned["owner_dimensions"] == {"procedure_length": "low"}
    assert owned["owner_notes"] == "Reviewed in the paper pilot."
    assert all(
        question["owner_difficulty"] is None for question in dataset["questions"][1:]
    )


def test_review_sheet_mentions_every_question():
    sheet = builder.render_review_sheet({"questions": QUESTIONS})

    for question in QUESTIONS:
        assert f"## {question['question_id']}" in sheet
        assert f"**Question.** {question['instance']['question']}" in sheet
    assert sheet.count("Your level:") == len(QUESTIONS)
