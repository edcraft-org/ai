"""Correctness, blinding and review integrity for the issue-42 reference set."""

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
def dataset(tmp_path):
    destination = tmp_path / "set"
    shutil.copytree(reference.DEFAULT_SET, destination)
    return destination


@pytest.fixture
def packet():
    questions, manifest = reference.load_set(reference.DEFAULT_SET)
    return reference.make_packet(reference.DEFAULT_SET, questions, manifest)


def completed_review(packet):
    review = reference.blank_review(packet, "test-human")
    review["independent_blinded_review"] = True
    for rating in review["ratings"]:
        rating.update(
            status="reviewed",
            estimated_difficulty="medium",
            confidence="medium",
            solution_reasoning="Concrete trace supplied by the test reviewer.",
            concepts_and_dependencies="An update depends on an earlier value.",
            shortcuts="None identified in this synthetic test rating.",
            nearest_anchor="Medium anchor: organised tracing.",
            option_evidence={label: "Test option evidence." for label in "ABCD"},
            dimensions={
                dimension: {"rating": "moderate", "reason": "Test reason."}
                for dimension in reference.DIMENSIONS
            },
        )
    return review


def test_full_set_execution_and_family_split():
    questions, manifest = reference.load_set(reference.DEFAULT_SET)
    evidence = reference.checked_evidence(reference.DEFAULT_SET, questions, manifest)
    assert reference.verify_questions(questions) == evidence["records"]
    assert len(questions) == 30
    assert len({entry["family_id"] for entry in manifest["items"]}) == 15
    assert Counter(e["split"] for e in manifest["items"]) == {
        "development": 18,
        "held_out": 12,
    }
    assert Counter(e["topic"] for e in manifest["items"]) == {
        "arithmetic": 6,
        "conditionals": 6,
        "loops": 6,
        "functions": 6,
        "lists": 6,
    }
    assert {q.answer_target for q in questions} == {
        "return_value",
        "branch_executions",
        "loop_iterations",
        "loop_executions",
        "function_calls",
    }
    for entry in manifest["items"]:
        source = entry["provenance"]
        if source["path"]:
            data = (reference.ROOT / source["path"]).read_bytes()
            assert reference.hashlib.sha256(data).hexdigest() == source["source_sha256"]


def test_packet_uses_only_blinded_fields(packet):
    assert len(packet["questions"]) == 30
    hidden = (
        "requested_difficulty",
        "generator",
        "provenance",
        "distractor_hypotheses",
        "family_id",
        "split",
        "question_id",
        "source_revision",
        "topic",
    )
    serialized = json.dumps(packet)
    assert all(f'"{field}"' not in serialized for field in hidden)
    assert [q["review_id"] for q in packet["questions"]] == [
        f"Q{i:02}" for i in range(1, 31)
    ]
    assert all(
        "verified_answer" in q and "trace_summary" in q for q in packet["questions"]
    )
    original = copy.deepcopy(packet)
    original.pop("packet_sha256")
    assert packet["packet_sha256"] == reference.digest(original)


def test_pending_human_ratings_do_not_become_references(packet):
    review = reference.blank_review(packet, "keith")
    validated, _, _, _ = reference.validate_review(reference.DEFAULT_SET, review)
    assert all(rating.status == "pending" for rating in validated.ratings)
    assert all(rating.estimated_difficulty is None for rating in validated.ratings)
    with pytest.raises(ValueError, match="finish and freeze"):
        reference.compare_review(reference.DEFAULT_SET, review)


def test_partial_draft_estimate_is_retained_without_revealing_request(packet):
    review = reference.blank_review(packet, "keith")
    review["ratings"][0]["estimated_difficulty"] = "hard"
    validated, _, _, _ = reference.validate_review(reference.DEFAULT_SET, review)
    assert reference.match_decision(validated.ratings[0], "easy") is None
    with pytest.raises(ValueError, match="finish and freeze"):
        reference.compare_review(reference.DEFAULT_SET, review)


def test_comparison_preserves_original_review_and_discloses_single_reviewer(packet):
    review = completed_review(packet)
    original = copy.deepcopy(review)
    report = reference.compare_review(reference.DEFAULT_SET, review)
    assert review == original
    assert report["review_sha256"] == reference.digest(review)
    assert report["reference_type"] == "single_human_reviewer"
    assert report["human_human_agreement"] is None
    assert report["observed_learner_performance"] is None
    assert report["reviewed_count"] == 30
    assert report["pending_count"] == 0
    assert {c["difficulty_match"] for c in report["comparisons"]} == {
        "matches",
        "too_easy",
        "too_hard",
    }


@pytest.mark.parametrize(
    ("estimate", "requested", "confidence", "alternatives", "expected"),
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
def test_matching_rule(packet, estimate, requested, confidence, alternatives, expected):
    rating = completed_review(packet)["ratings"][0]
    rating.update(
        estimated_difficulty=estimate,
        confidence=confidence,
        alternative_levels=alternatives,
        uncertainty_reason="Plausible alternative or insufficient evidence.",
    )
    assert reference.match_decision(
        reference.Rating.model_validate(rating), requested
    ) == (expected)


@pytest.mark.parametrize("field", ["packet_sha256", "rubric_sha256", "rubric_version"])
def test_stale_review_is_rejected(packet, field):
    review = completed_review(packet)
    review[field] = "stale"
    with pytest.raises(ValueError, match="stale review"):
        reference.validate_review(reference.DEFAULT_SET, review)


def test_no_model_ratings_or_unattested_humans(packet):
    review = completed_review(packet)
    review["reviewer_kind"] = "model"
    with pytest.raises(ValidationError):
        reference.validate_review(reference.DEFAULT_SET, review)
    review["reviewer_kind"] = "human"
    review["independent_blinded_review"] = False
    with pytest.raises(ValueError, match="attest"):
        reference.validate_review(reference.DEFAULT_SET, review)


@pytest.mark.parametrize("problem", ["duplicate", "missing", "edited", "reasons"])
def test_invalid_review_rejected(packet, problem):
    review = completed_review(packet)
    if problem == "duplicate":
        review["ratings"].append(review["ratings"][0])
    elif problem == "missing":
        review["ratings"].pop()
    elif problem == "edited":
        review["ratings"][0]["question_sha256"] = "edited"
    else:
        review["ratings"][0]["option_evidence"]["A"] = ""
    with pytest.raises(ValueError):
        reference.validate_review(reference.DEFAULT_SET, review)


def test_unknown_human_label_is_retained_as_uncertain(packet):
    review = completed_review(packet)
    review["ratings"][0].update(
        estimated_difficulty=None,
        uncertainty_reason="No anchor fits confidently.",
    )
    report = reference.compare_review(reference.DEFAULT_SET, review)
    assert report["comparisons"][0]["difficulty_match"] == "uncertain"
    assert report["comparisons"][0]["estimated_difficulty"] is None


def test_family_leak_rejected(dataset):
    path = dataset / "manifest.json"
    manifest = reference.read_json(path)
    manifest["items"][1]["split"] = "held_out"
    reference.write_json(path, manifest)
    with pytest.raises(ValueError, match="family leaks"):
        reference.load_set(dataset)


def test_edited_question_invalidates_evidence(dataset):
    path = dataset / "questions.json"
    data = reference.read_json(path)
    data["questions"][0]["question"] += " Edited."
    reference.write_json(path, data)
    questions, manifest = reference.load_set(dataset)
    with pytest.raises(ValueError, match="stale question evidence"):
        reference.make_packet(dataset, questions, manifest)


def test_colliding_or_boolean_options_rejected():
    questions, _ = reference.load_set(reference.DEFAULT_SET)
    item = questions[0].model_dump()
    item["options"][1]["value"] = item["options"][0]["value"]
    with pytest.raises(ValidationError, match="collide"):
        reference.Question.model_validate(item)
    item["options"][1]["value"] = True
    with pytest.raises(ValidationError):
        reference.Question.model_validate(item)


def test_failed_execution_cannot_supply_answer(monkeypatch):
    questions, _ = reference.load_set(reference.DEFAULT_SET)
    monkeypatch.setattr(
        reference.LocalPythonTool,
        "execute_batch",
        lambda *args, **kwargs: [
            ExecutionResult(ok=False, error_message="execution timeout")
        ],
    )
    with pytest.raises(ValueError, match="execution timeout"):
        reference.verify_questions(questions[:1])


def test_execution_answer_mismatch_rejected(monkeypatch):
    questions, _ = reference.load_set(reference.DEFAULT_SET)
    monkeypatch.setattr(
        reference.LocalPythonTool,
        "execute_batch",
        lambda *args, **kwargs: [
            ExecutionResult(ok=True, answer=999, trace_summary={})
        ],
    )
    with pytest.raises(ValueError, match="differs"):
        reference.verify_questions(questions[:1])


def test_evidence_tampering_rejected(dataset):
    path = dataset / "technical-evidence.json"
    data = reference.read_json(path)
    data["records"][0]["verified_answer"] = 999
    reference.write_json(path, data)
    questions, manifest = reference.load_set(dataset)
    with pytest.raises(ValueError, match="invalid technical evidence"):
        reference.make_packet(dataset, questions, manifest)


def test_prepare_review_exports_safe_self_contained_form(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "difficulty_reference.py",
            "prepare-review",
            "--reviewer",
            "ui-test",
            "--output",
            str(tmp_path),
        ],
    )
    reference.main()
    packet = reference.read_json(tmp_path / "packet.json")
    review = reference.read_json(tmp_path / "review.json")
    reference.validate_review(reference.DEFAULT_SET, review)
    html = (tmp_path / "review.html").read_text()
    assert "__PAYLOAD__" not in html
    assert "Show ratings JSON" in html
    assert "requested_difficulty" not in html
    payload_start = '<script id="payload" type="application/json">'
    payload = json.loads(html.split(payload_start, 1)[1].split("</script>", 1)[0])
    assert payload["packet"] == packet
    assert payload["review"] == review
    assert (
        payload["rubric_text"]
        == (reference.ROOT / "docs/difficulty-rubric.md").read_text()
    )
