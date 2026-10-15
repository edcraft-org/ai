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
            rating_reason="Linked updates require a small organised trace.",
            dimensions={
                dimension: {"rating": "moderate"} for dimension in reference.DIMENSIONS
            },
        )
    return review


def test_full_set_execution_and_family_split():
    questions, manifest = reference.load_set(reference.DEFAULT_SET)
    evidence = reference.checked_evidence(reference.DEFAULT_SET, questions, manifest)
    assert reference.verify_questions(questions) == evidence["records"]
    assert len(questions) == 30
    assert len({entry["family_id"] for entry in manifest["items"]}) == 30
    assert len({reference.code_family_fingerprint(q.code) for q in questions}) == 30
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
        review["ratings"][0]["rating_reason"] = ""
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
    manifest["items"][1]["family_id"] = manifest["items"][0]["family_id"]
    manifest["items"][1]["split"] = "held_out"
    reference.write_json(path, manifest)
    with pytest.raises(ValueError, match="family leaks"):
        reference.load_set(dataset)


def test_primary_collection_rejects_same_family_variants(dataset):
    path = dataset / "manifest.json"
    manifest = reference.read_json(path)
    manifest["items"][1]["family_id"] = manifest["items"][0]["family_id"]
    reference.write_json(path, manifest)
    with pytest.raises(ValueError, match="one question per family"):
        reference.load_set(dataset)


def test_renamed_literal_and_formatting_clones_cannot_cross_families(dataset):
    path = dataset / "questions.json"
    data = reference.read_json(path)
    data["questions"][1]["code"] = (
        "# A cosmetic rewrite of the first question\n"
        "def renamed(first, second, third):\n    return (first + second) - third\n"
    )
    reference.write_json(path, data)
    with pytest.raises(ValueError, match="normalised code clone"):
        reference.load_set(dataset)
    first = "def f(x):\n    return x + 1"
    renamed = "def g(y):\n    return y + 42"
    assert reference.code_family_fingerprint(
        first
    ) == reference.code_family_fingerprint(renamed)
    assert reference.code_family_fingerprint(
        first
    ) != reference.code_family_fingerprint("def g(y):\n    return y - 42")


@pytest.mark.parametrize("problem", ["source", "code", "license", "revision"])
def test_external_source_and_license_integrity(dataset, problem):
    if problem == "source":
        path = dataset / "sources/cruxeval-selected.jsonl"
        path.write_text(path.read_text().replace('"sample_197"', '"sample_changed"'))
    elif problem == "license":
        (dataset / "sources/CRUXEval-LICENSE").write_text("removed")
    elif problem == "code":
        path = dataset / "questions.json"
        data = reference.read_json(path)
        data["questions"][15]["code"] += "\n# edited source\n"
        reference.write_json(path, data)
    else:
        path = dataset / "manifest.json"
        data = reference.read_json(path)
        data["items"][15]["provenance"]["source_revision"] = "different"
        reference.write_json(path, data)
    with pytest.raises(ValueError, match="external"):
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


def recommendations():
    questions, manifest = reference.load_set(reference.DEFAULT_SET)
    return reference.load_recommendations(reference.DEFAULT_SET, questions, manifest)


def confirmed_assisted_review(packet):
    review = reference.assisted_review(packet, "test-human", recommendations())
    review["assisted_review_confirmed"] = True
    for rating in review["ratings"]:
        rating.update(status="reviewed", human_decision="approved")
    return review


def test_short_human_review_needs_no_solution_or_option_explanations(packet):
    review = completed_review(packet)
    absent = {
        "solution_reasoning",
        "concepts_and_dependencies",
        "shortcuts",
        "nearest_anchor",
        "option_evidence",
    }
    assert absent.isdisjoint(review["ratings"][0])
    validated, _, _, _ = reference.validate_review(reference.DEFAULT_SET, review)
    assert all(d.reason == "" for d in validated.ratings[0].dimensions.values())
    review["ratings"][0]["dimensions"]["execution_burden"]["rating"] = None
    with pytest.raises(ValueError, match="choose all four"):
        reference.validate_review(reference.DEFAULT_SET, review)


def test_detailed_legacy_reviews_are_preserved(packet):
    review = completed_review(packet)
    review.pop("review_schema_version")
    for rating in review["ratings"]:
        rating.pop("rating_reason")
        rating.update(
            solution_reasoning="Original human solution note.",
            concepts_and_dependencies="Original dependency note.",
            shortcuts="Original shortcut note.",
            nearest_anchor="Original anchor note.",
            option_evidence={label: "Original option note." for label in "ABCD"},
        )
        for dimension in rating["dimensions"].values():
            dimension["reason"] = "Original dimension note."
    original = copy.deepcopy(review)
    report = reference.compare_review(reference.DEFAULT_SET, review)
    assert review == original
    assert report["review_sha256"] == reference.digest(original)
    assert report["independent_reference"] is True


def test_ai_recommendations_cover_all_items_without_human_labels(packet):
    proposed = recommendations()
    assert len(proposed["records"]) == 30
    assert proposed["assessor_kind"] == "AI"
    assert proposed["independent_blinded_assessment"] is False
    review = reference.assisted_review(packet, "keith", proposed)
    assert review["independent_blinded_review"] is False
    assert not review["assisted_review_confirmed"]
    assert all(
        r["status"] == "pending" and r["human_decision"] == "pending"
        for r in review["ratings"]
    )
    assert all(r["rating_reason"] == "" for r in review["ratings"])
    reference.validate_review(reference.DEFAULT_SET, review)
    with pytest.raises(ValueError, match="finish and freeze"):
        reference.compare_review(reference.DEFAULT_SET, review)


def test_assisted_approvals_need_no_retyped_ai_reason_and_disclose_assistance(packet):
    review = confirmed_assisted_review(packet)
    report = reference.compare_review(reference.DEFAULT_SET, review)
    assert report["reference_type"] == "ai_assisted_single_human_reviewer"
    assert report["independent_reference"] is False
    assert report["human_decisions"] == {"approved": 30}
    assert report["recommendations_sha256"] == reference.digest(recommendations())
    assert all(r["rating_reason"] == "" for r in review["ratings"])
    assert report["review_sha256"] == reference.digest(review)


@pytest.mark.parametrize(
    "problem",
    [
        "not_confirmed",
        "blind_claim",
        "no_decision",
        "changed_proposals",
        "changed_approval",
    ],
)
def test_assisted_provenance_cannot_be_misrepresented(packet, problem):
    review = confirmed_assisted_review(packet)
    if problem == "not_confirmed":
        review["assisted_review_confirmed"] = False
    elif problem == "blind_claim":
        review["independent_blinded_review"] = True
    elif problem == "no_decision":
        review["ratings"][0]["human_decision"] = "pending"
    elif problem == "changed_proposals":
        review["recommendations_sha256"] = "changed"
    else:
        first = review["ratings"][0]
        first["estimated_difficulty"] = (
            "hard" if first["estimated_difficulty"] != "hard" else "easy"
        )
    with pytest.raises(ValueError):
        reference.validate_review(reference.DEFAULT_SET, review)


def test_assisted_human_correction_and_abstention_are_separate_from_ai(packet):
    review = confirmed_assisted_review(packet)
    first = review["ratings"][0]
    first.update(
        estimated_difficulty="hard"
        if first["estimated_difficulty"] != "hard"
        else "easy",
        human_decision="corrected",
        rating_reason="Human reviewer sees more coordination than the proposal.",
    )
    second = review["ratings"][1]
    second.update(
        estimated_difficulty=None,
        confidence="low",
        human_decision="uncertain",
        rating_reason="Human reviewer cannot place this question confidently.",
    )
    original_proposals = reference.read_json(
        reference.DEFAULT_SET / "ai-recommendations.json"
    )
    report = reference.compare_review(reference.DEFAULT_SET, review)
    assert report["human_decisions"] == {"corrected": 1, "uncertain": 1, "approved": 28}
    assert report["comparisons"][1]["difficulty_match"] == "uncertain"
    assert (
        reference.read_json(reference.DEFAULT_SET / "ai-recommendations.json")
        == original_proposals
    )
    first["rating_reason"] = ""
    with pytest.raises(ValueError, match="short human note"):
        reference.validate_review(reference.DEFAULT_SET, review)


def test_ai_proposal_question_edits_invalidate_approval(dataset, packet):
    review = confirmed_assisted_review(packet)
    path = dataset / "ai-recommendations.json"
    proposed = reference.read_json(path)
    proposed["records"][0]["question_sha256"] = "changed"
    reference.write_json(path, proposed)
    with pytest.raises(ValueError, match="question changed"):
        reference.validate_review(dataset, review)


def test_assisted_export_cannot_be_renamed_as_independent(packet):
    review = confirmed_assisted_review(packet)
    review["review_schema_version"] = reference.REVIEW_SCHEMA
    review["independent_blinded_review"] = True
    for rating in review["ratings"]:
        rating["rating_reason"] = "A purported independent note."
    with pytest.raises(ValueError, match="relabelled independent"):
        reference.validate_review(reference.DEFAULT_SET, review)


def test_regeneration_preserves_saved_reviews_and_archives_format_switches(
    monkeypatch, tmp_path, packet
):
    saved = completed_review(packet)
    reference.write_json(tmp_path / "review.json", saved)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "difficulty_reference.py",
            "prepare-review",
            "--reviewer",
            "test-human",
            "--output",
            str(tmp_path),
        ],
    )
    reference.main()
    assert reference.read_json(tmp_path / "review.json") == saved
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "difficulty_reference.py",
            "prepare-review",
            "--reviewer",
            "test-human",
            "--assisted",
            "--output",
            str(tmp_path),
        ],
    )
    reference.main()
    assert (
        reference.read_json(
            tmp_path / f"review.archive-{reference.digest(saved)[:12]}.json"
        )
        == saved
    )
    assisted = reference.read_json(tmp_path / "review.json")
    assert assisted["review_schema_version"] == reference.ASSISTED_REVIEW_SCHEMA
    assert all(r["status"] == "pending" for r in assisted["ratings"])


def test_original_review_is_preserved_and_only_unchanged_decisions_are_carried():
    source = reference.ROOT / "reference_sets/python_tracing_v1"
    original_path = source / "reviews/keith-2026-10-15.json"
    original_bytes = original_path.read_bytes()
    original = reference.read_json(original_path)
    review, audit = reference.carry_forward_review(
        source, original, reference.DEFAULT_SET
    )
    validated, _, _, _ = reference.validate_review(reference.DEFAULT_SET, review)
    assert audit["carried_count"] == 15
    assert audit["pending_count"] == 15
    assert audit["source_review_sha256"] == reference.digest(original)
    assert Counter(r.human_decision for r in validated.ratings) == {
        "approved": 13,
        "corrected": 2,
        "pending": 15,
    }
    previous = {r["question_sha256"]: r for r in original["ratings"]}
    for rating in review["ratings"]:
        if rating["status"] == "pending":
            assert rating["human_decision"] == "pending"
            assert rating["question_sha256"] not in previous
        else:
            old = previous[rating["question_sha256"]]
            assert {k: v for k, v in rating.items() if k != "review_id"} == {
                k: v for k, v in old.items() if k != "review_id"
            }
    assert original_path.read_bytes() == original_bytes
    with pytest.raises(ValueError, match="finish and freeze"):
        reference.compare_review(reference.DEFAULT_SET, review)


@pytest.mark.parametrize("change", ["proposal", "question"])
def test_changed_question_or_proposal_needs_fresh_approval(dataset, change):
    source = reference.ROOT / "reference_sets/python_tracing_v1"
    original = reference.read_json(source / "reviews/keith-2026-10-15.json")
    proposal_path = dataset / "ai-recommendations.json"
    proposals = reference.read_json(proposal_path)
    if change == "proposal":
        proposals["records"][0]["rating_reason"] += " Revised recommendation."
    else:
        question_path = dataset / "questions.json"
        data = reference.read_json(question_path)
        data["questions"][0]["question"] += " Check carefully."
        reference.write_json(question_path, data)
        new_hash = reference.digest(data["questions"][0])
        proposals["records"][0]["question_sha256"] = new_hash
        evidence_path = dataset / "technical-evidence.json"
        evidence = reference.read_json(evidence_path)
        evidence["questions_sha256"] = reference.digest(data)
        evidence["records"][0]["question_sha256"] = new_hash
        reference.write_json(evidence_path, evidence)
    reference.write_json(proposal_path, proposals)
    review, audit = reference.carry_forward_review(source, original, dataset)
    assert audit["carried_count"] == 14
    assert audit["pending_count"] == 16
    changed_hash = proposals["records"][0]["question_sha256"]
    assert (
        next(r for r in review["ratings"] if r["question_sha256"] == changed_hash)[
            "status"
        ]
        == "pending"
    )


def test_carry_forward_rejects_stale_or_changed_assistance_context(dataset):
    source = reference.ROOT / "reference_sets/python_tracing_v1"
    original = reference.read_json(source / "reviews/keith-2026-10-15.json")
    original["packet_sha256"] = "stale"
    with pytest.raises(ValueError, match="stale review"):
        reference.carry_forward_review(source, original, dataset)
    original = reference.read_json(source / "reviews/keith-2026-10-15.json")
    path = dataset / "ai-recommendations.json"
    proposals = reference.read_json(path)
    proposals["source_context"] = "Different assistance disclosure."
    reference.write_json(path, proposals)
    with pytest.raises(ValueError, match="context changed"):
        reference.carry_forward_review(source, original, dataset)


def test_carry_cli_never_overwrites_a_saved_review(monkeypatch, tmp_path):
    path = tmp_path / "review.json"
    path.write_text('"existing review"\n')
    source = reference.ROOT / "reference_sets/python_tracing_v1"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "difficulty_reference.py",
            "carry-review",
            "--source-set",
            str(source),
            str(source / "reviews/keith-2026-10-15.json"),
            "--output",
            str(tmp_path),
        ],
    )
    with pytest.raises(ValueError, match="already exists"):
        reference.main()
    assert path.read_text() == '"existing review"\n'


def test_committed_partial_review_and_transfer_audit_replay_exactly():
    source = reference.ROOT / "reference_sets/python_tracing_v1"
    original_path = source / "reviews/keith-2026-10-15.json"
    review, audit = reference.carry_forward_review(
        source, reference.read_json(original_path), reference.DEFAULT_SET
    )
    archived = reference.read_json(
        reference.DEFAULT_SET / "reviews/keith-2026-10-15-carried.json"
    )
    saved_audit = reference.read_json(
        reference.DEFAULT_SET / "reviews/carry-forward.json"
    )
    assert archived == review
    assert all(saved_audit[key] == value for key, value in audit.items())
    assert (
        saved_audit["source_review_file_sha256"]
        == reference.hashlib.sha256(original_path.read_bytes()).hexdigest()
    )


def test_completed_human_reference_and_comparison_are_bound_to_original_export():
    directory = reference.DEFAULT_SET
    questions, manifest = reference.load_set(directory)
    metadata = manifest["completed_review"]
    path = directory / metadata["path"]
    original = reference.read_json(path)
    review, _, _, _ = reference.validate_review(directory, original)
    assert manifest["review_status"] == "completed_assisted_single_human_review"
    assert len(questions) == metadata["reviewed_count"] == 30
    assert metadata["pending_count"] == 0
    assert all(r.status == "reviewed" for r in review.ratings)
    assert Counter(r.human_decision for r in review.ratings) == {
        "approved": 27,
        "corrected": 3,
    }
    assert reference.digest(original) == metadata["review_sha256"]
    assert (
        reference.hashlib.sha256(path.read_bytes()).hexdigest()
        == metadata["source_file_sha256"]
    )
    report = reference.compare_review(directory, original)
    assert report == reference.read_json(directory / metadata["comparison_path"])
    assert report["independent_reference"] is False
    assert report["observed_learner_performance"] is None
    assert Counter(item["difficulty_match"] for item in report["comparisons"]) == {
        "matches": 13,
        "too_easy": 3,
        "uncertain": 14,
    }


def test_follow_up_audit_covers_frozen_items_and_replays_shortcut_evidence():
    from edcraft_validator.tools.python_execution import LocalPythonTool

    directory = reference.DEFAULT_SET
    audit = reference.read_json(directory / "quality-audit-2026-10-15.json")
    questions, manifest = reference.load_set(directory)
    original = reference.read_json(directory / manifest["completed_review"]["path"])
    by_id = {q.question_id: q for q in questions}
    assert audit["review_sha256"] == reference.digest(original)
    assert audit["questions_sha256"] == reference.digest(
        reference.read_json(directory / "questions.json")
    )
    assert audit["assessor_kind"] == "AI"
    assert len(audit["records"]) == len(questions) == 30
    assert {r["question_id"] for r in audit["records"]} == set(by_id)
    assert all(not r["human_approval_of_audit"] for r in audit["records"])
    for record in audit["records"]:
        question = by_id[record["question_id"]]
        assert record["question_sha256"] == reference.digest(question.model_dump())
        assert record["verified_correct_option"] == question.correct_option
    choices = {}
    for observation in audit["shortcut_observations"]["observations"]:
        result = LocalPythonTool().execute_batch(
            observation["observer_code"],
            observation["entry_function"],
            [observation["inputs"]],
            timeout_seconds=2,
        )[0]
        assert result.ok
        assert result.answer == observation["observed_answer"]
        rule = observation["option_filter"]
        suffix = rule == "ends_with_observed_string"
        fragment = (
            "".join(result.answer)
            if rule == ("starts_with_joined_observed_prefixes")
            else result.answer
        )
        compatible = [
            option.id
            for option in by_id[observation["question_id"]].options
            if (
                option.value.endswith(fragment)
                if suffix
                else option.value.startswith(fragment)
            )
        ]
        assert compatible == observation["compatible_options"]
        choices[observation["observation_id"]] = set(compatible)
    assert choices["Q14-first-two-updates"] == {"B"}
    assert choices["Q09-first-loop-update"] == {"A"}
    assert choices["Q30-first-two-pending-prefixes"] & choices["Q30-base-return"] == {
        "B"
    }
