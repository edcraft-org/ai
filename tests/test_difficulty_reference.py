"""Frozen evaluation labels, answer verification, provenance and judge blinding."""

import copy
import json
import shutil
import sys
from collections import Counter

import pytest
from pydantic import ValidationError

from edcraft_validator.tools.python_execution import ExecutionResult
from scripts import difficulty_reference as reference


@pytest.fixture
def dataset_copy(tmp_path):
    destination = tmp_path / "dataset"
    shutil.copytree(reference.DEFAULT_SET, destination)
    return destination / "dataset.json"


def read_data(path=reference.DEFAULT_DATASET):
    return json.loads(path.read_text())


def write_data(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_only_one_final_dataset_is_present():
    directories = sorted(p.name for p in (reference.ROOT / "reference_sets").iterdir())
    assert directories == ["python_tracing"]
    assert sorted(p.name for p in reference.DEFAULT_SET.iterdir()) == [
        "CRUXEval-LICENSE",
        "README.md",
        "dataset.json",
    ]


def test_frozen_categories_match_the_approved_review_exactly():
    dataset = reference.load_dataset()
    assert dataset.frozen
    assert dataset.approved_revision == "240704a008cfb1bb4fc405e9f2fd9e1512e42b24"
    assert dataset.approved_review_sha256 == (
        "de61d45a4cac39c3b41fac5dc43642a87ff001d3b1d67d447a2f3daf8a92b18c"
    )
    labels = {
        q.question_id: {
            k: q.model_dump()[k]
            for k in [
                "difficulty",
                "dimensions",
                "topic",
                "split",
            ]
        }
        for q in dataset.questions
    }
    assert (
        reference.digest(labels)
        == "981c9529e283e2c86103ae9ce7e0e37fbeb7849609459c8ad6de2a2ca2e6b5ec"
    )
    assert Counter(q.difficulty for q in dataset.questions) == {
        "easy": 13,
        "medium": 11,
        "hard": 6,
    }
    assert Counter(q.split for q in dataset.questions) == {
        "development": 18,
        "held_out": 12,
    }
    assert Counter(q.topic for q in dataset.questions) == {
        "arithmetic": 6,
        "conditionals": 6,
        "loops": 6,
        "functions": 6,
        "lists": 6,
    }
    assert len({q.family_id for q in dataset.questions}) == 30
    assert (
        len({reference.code_family_fingerprint(q.code) for q in dataset.questions})
        == 30
    )
    assert {q.answer_target for q in dataset.questions} == {
        "return_value",
        "branch_executions",
        "loop_executions",
        "loop_iterations",
        "function_calls",
    }
    assert {q.review_id for q in dataset.questions if q.difficulty == "hard"} == {
        "Q01",
        "Q11",
        "Q12",
        "Q20",
        "Q23",
        "Q29",
    }
    assert all(
        q.difficulty == "hard"
        for q in dataset.questions
        if q.review_id
        in {
            "Q01",
            "Q11",
            "Q12",
            "Q20",
            "Q23",
            "Q29",
        }
    )
    assert all(
        q.review_notes.alternative_levels == ["medium"]
        for q in dataset.questions
        if q.difficulty == "hard"
    )
    corrected = next(q for q in dataset.questions if q.review_id == "Q19")
    assert corrected.difficulty == "easy"
    assert corrected.dimensions.execution_burden == "moderate"
    assert corrected.reason_source == "human_correction"
    assert Counter(q.review_notes.human_decision for q in dataset.questions) == {
        "approved": 29,
        "corrected": 1,
    }
    assert dataset.reference_type == "ai_assisted_single_human_reviewer"


def test_every_answer_and_trace_replays_without_changing_labels():
    before = reference.DEFAULT_DATASET.read_bytes()
    result = reference.verify_dataset()
    assert result["verified"] == 30 and result["frozen"] is True
    assert result["difficulty"] == {"easy": 13, "medium": 11, "hard": 6}
    assert result["sha256"] == reference.FROZEN_DATASET_SHA256
    assert reference.DEFAULT_DATASET.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("difficulty", "easy"),
        ("topic", "loops"),
        ("split", "held_out"),
        ("dimensions", {k: "low" for k in reference.DIMENSIONS}),
        ("question", "Changed question"),
        ("inputs", {"values": [1, 2]}),
        ("solution", "Changed explanation"),
    ],
)
def test_frozen_data_edits_are_rejected(dataset_copy, field, value):
    data = read_data(dataset_copy)
    assert data["questions"][0][field] != value
    data["questions"][0][field] = value
    write_data(dataset_copy, data)
    with pytest.raises(ValueError, match="frozen dataset changed"):
        reference.load_dataset(dataset_copy)


def test_swapping_labels_without_changing_totals_is_rejected(dataset_copy):
    data = read_data(dataset_copy)
    hard = next(q for q in data["questions"] if q["difficulty"] == "hard")
    easy = next(q for q in data["questions"] if q["difficulty"] == "easy")
    hard["difficulty"], easy["difficulty"] = easy["difficulty"], hard["difficulty"]
    write_data(dataset_copy, data)
    with pytest.raises(ValueError, match="frozen dataset changed"):
        reference.load_dataset(dataset_copy)


def test_question_categories_cannot_be_reassigned_in_memory():
    item = reference.load_dataset().questions[0]
    with pytest.raises(ValidationError, match="frozen"):
        item.difficulty = "easy"
    with pytest.raises(ValidationError, match="frozen"):
        item.dimensions.changing_state = "low"
    with pytest.raises(ValidationError, match="frozen"):
        item.split = "held_out"


@pytest.mark.parametrize("problem", ["duplicate_id", "missing", "family", "clone"])
def test_duplicate_questions_and_split_leakage_are_rejected(dataset_copy, problem):
    data = read_data(dataset_copy)
    first, second = data["questions"][:2]
    if problem == "duplicate_id":
        second["question_id"] = first["question_id"]
    elif problem == "missing":
        data["questions"].pop()
    elif problem == "family":
        second["family_id"] = first["family_id"]
    else:
        second["code"] = "# cosmetic clone\n" + first["code"]
    write_data(dataset_copy, data)
    with pytest.raises(ValueError):
        reference.load_dataset(dataset_copy)


def test_clone_screen_ignores_names_and_literals_but_preserves_operators():
    assert reference.code_family_fingerprint("def f(x):\n    return x + 1") == (
        reference.code_family_fingerprint("def g(y):\n    return y + 42")
    )
    assert reference.code_family_fingerprint("def f(x):\n    return x + 1") != (
        reference.code_family_fingerprint("def g(y):\n    return y - 42")
    )


@pytest.mark.parametrize("problem", ["license", "source_code", "revision", "record"])
def test_source_and_license_integrity(dataset_copy, problem):
    if problem == "license":
        (dataset_copy.parent / "CRUXEval-LICENSE").write_text("removed")
    else:
        data = read_data(dataset_copy)
        item = next(
            q
            for q in data["questions"]
            if q["provenance"]["kind"] == "cruxeval_adaptation"
        )
        if problem == "source_code":
            item["code"] += "\n# changed"
        elif problem == "revision":
            item["provenance"]["source_revision"] = "different"
        else:
            item["provenance"].pop("source_record_sha256")
        write_data(dataset_copy, data)
    with pytest.raises(ValueError, match="source|license"):
        reference.load_dataset(dataset_copy)


@pytest.mark.parametrize(
    "problem", ["options", "boolean", "answer", "count", "dimension"]
)
def test_invalid_reference_records_cannot_supply_ground_truth(dataset_copy, problem):
    data = read_data(dataset_copy)
    item = data["questions"][0]
    if problem == "options":
        item["options"][1]["value"] = item["options"][0]["value"]
    elif problem == "boolean":
        item["options"][1]["value"] = True
    elif problem == "answer":
        item["verified_answer"] = 999
    elif problem == "count":
        item = next(
            q for q in data["questions"] if q["answer_target"] == "loop_executions"
        )
        item["trace_summary"]["loop_executions"] = 999
    else:
        item["dimensions"].pop("changing_state")
    write_data(dataset_copy, data)
    with pytest.raises(ValueError):
        reference.load_dataset(dataset_copy)


def test_judge_payload_never_includes_ground_truth_categories_or_review_notes():
    dataset = reference.load_dataset()
    for item in dataset.questions:
        original = copy.deepcopy(item.model_dump())
        payload = reference.question_for_judge(item)
        assert set(payload) == {
            "code",
            "entry_function",
            "inputs",
            "question",
            "answer_target",
            "options",
            "correct_option",
        }
        assert payload["code"] == item.code
        assert len(payload["options"]) == 4
        assert item.model_dump() == original
        assert "difficulty" not in payload
        assert "solution" not in payload
        assert "dimensions" not in payload


@pytest.mark.parametrize("failure", ["timeout", "wrong_answer", "changed_trace"])
def test_execution_failures_never_rewrite_reference_labels(monkeypatch, failure):
    item = reference.load_dataset().questions[0]
    before = reference.DEFAULT_DATASET.read_bytes()
    by_code = {q.code: q for q in reference.load_dataset().questions}

    def execute(self, code, *args, **kwargs):
        current = by_code[code]
        summary = current.trace_summary.copy()
        if failure == "timeout":
            return [ExecutionResult(ok=False, error_message="execution timeout")]
        if failure == "changed_trace" and current.question_id == item.question_id:
            summary["loop_iterations"] += 1
        return [
            ExecutionResult(
                ok=True,
                answer=999 if failure == "wrong_answer" else current.verified_answer,
                trace_summary=summary,
            )
        ]

    monkeypatch.setattr(reference.LocalPythonTool, "execute_batch", execute)
    expected = {
        "timeout": "execution timeout",
        "wrong_answer": "differs",
        "changed_trace": "execution trace changed",
    }[failure]
    with pytest.raises(ValueError, match=expected):
        reference.verify_dataset()
    assert reference.DEFAULT_DATASET.read_bytes() == before


def test_verify_cli_is_read_only(monkeypatch, capsys):
    before = reference.DEFAULT_DATASET.read_bytes()
    monkeypatch.setattr(sys, "argv", ["difficulty_reference.py", "verify"])
    reference.main()
    assert json.loads(capsys.readouterr().out)["verified"] == 30
    assert reference.DEFAULT_DATASET.read_bytes() == before


@pytest.mark.parametrize(
    "command",
    [
        "prepare-review",
        "carry-review",
        "validate-review",
        "compare-review",
        "--write-evidence",
    ],
)
def test_retired_review_and_overwrite_commands_are_unavailable(monkeypatch, command):
    before = reference.DEFAULT_DATASET.read_bytes()
    monkeypatch.setattr(sys, "argv", ["difficulty_reference.py", command])
    with pytest.raises(SystemExit):
        reference.main()
    assert reference.DEFAULT_DATASET.read_bytes() == before


@pytest.mark.parametrize(
    "estimate,requested,confidence,alternatives,expected",
    [
        ("easy", "easy", "high", [], "matches"),
        ("hard", "easy", "medium", [], "too_hard"),
        ("easy", "hard", "medium", [], "too_easy"),
        (None, "easy", "medium", [], "uncertain"),
        ("easy", "easy", "low", [], "uncertain"),
        ("easy", "easy", "medium", ["medium"], "uncertain"),
        ("easy", "hard", "medium", ["medium"], "too_easy"),
    ],
)
def test_live_assessment_matching_remains_separate_from_frozen_labels(
    estimate,
    requested,
    confidence,
    alternatives,
    expected,
):
    rating = reference.Rating.model_validate(
        {
            "review_id": "test",
            "question_sha256": "test",
            "status": "reviewed",
            "estimated_difficulty": estimate,
            "confidence": confidence,
            "alternative_levels": alternatives,
            "uncertainty_reason": "Boundary assessment.",
            "dimensions": {
                name: {"rating": "moderate"} for name in reference.DIMENSIONS
            },
            "quality_concerns": "",
        }
    )
    assert reference.match_decision(rating, requested) == expected
    rating.status = "pending"
    assert reference.match_decision(rating, requested) is None
