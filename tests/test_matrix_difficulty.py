"""Matrix reference integrity, evidence requirements and deterministic mapping."""

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.difficulty_trace import Trace
from scripts.evaluate_matrix_difficulty import (
    MatrixAssessment,
    build_request,
    normalize,
)

ROOT = Path(__file__).resolve().parents[1]


def assessment(events=5, state="low", concept="low", pattern=None):
    return {
        "event_ledger": [
            {
                "source_line": 2,
                "event_kind": "assignment",
                "multiplicity": events,
                "execution_evidence": "iterations",
            }
        ],
        "target_relevance_omissions": [],
        "carried_state_evidence": ["a is updated and read on the next iteration"],
        "changing_state": {"rating": state, "reason": "state evidence"},
        "dependency_chain": ["a -> guard -> update a"],
        "conceptual_high_pattern": pattern,
        "conceptual_interaction": {"rating": concept, "reason": "dependency evidence"},
        "unable_to_assess_reason": None,
    }


@pytest.mark.parametrize(
    "count,burden,overall",
    [
        (5, "low", "easy"),
        (6, "moderate", "medium"),
        (20, "moderate", "medium"),
        (21, "high", "medium"),
    ],
)
def test_execution_band_and_overall_are_derived_from_ledger(count, burden, overall):
    prediction, dimensions, total = normalize(assessment(count))
    assert total == count
    assert dimensions["execution_burden"] == burden
    assert prediction == overall


def test_high_state_is_medium_and_high_interaction_requires_supported_evidence():
    assert normalize(assessment(state="high"))[0] == "medium"
    with pytest.raises(ValidationError, match="named pattern"):
        MatrixAssessment.model_validate(assessment(concept="high"))
    valid = assessment(concept="high", pattern="state_control_feedback")
    assert normalize(MatrixAssessment.model_validate(valid).model_dump())[0] == "hard"
    valid["dependency_chain"] = []
    with pytest.raises(ValidationError, match="named pattern"):
        MatrixAssessment.model_validate(valid)


def test_unknown_or_missing_evidence_withholds_overall_and_zero_events_are_supported():
    valid = assessment()
    valid["event_ledger"] = []
    assert normalize(valid) == (
        "easy",
        dict.fromkeys(
            ("execution_burden", "changing_state", "conceptual_interaction"), "low"
        ),
        0,
    )
    valid["unable_to_assess_reason"] = "missing input"
    assert normalize(valid)[0] is None
    assert normalize(valid)[1]["execution_burden"] == "unknown"
    assert normalize(assessment(state="unknown"))[0] is None
    assert normalize(None) == (None, {}, None)
    valid = assessment(state="moderate")
    valid["carried_state_evidence"] = []
    with pytest.raises(ValidationError, match="explicit evidence"):
        MatrixAssessment.model_validate(valid)


def test_matrix_requests_are_blinded_and_no_free_overall_or_burden_label_is_requested():
    dataset = json.loads(
        (ROOT / "reference_sets/python_tracing/archive/dataset-v0.4.json").read_text()
    )
    q = dataset["questions"][0] | {"rating_evidence": "SECRET_RATING"}
    request = build_request(q, "RUBRIC")
    assert "SECRET_RATING" not in str(request.messages)
    body = json.loads(request.messages[1]["content"])["question"]
    assert "difficulty" not in body and "trace_event_count" not in body
    schema = request.response_model.model_json_schema()
    assert "estimated_difficulty" not in schema["properties"]
    assert "execution_burden" not in schema["properties"]
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_all_reference_items_are_reassessed_without_changing_question_content():
    folder = ROOT / "reference_sets/python_tracing"
    current = json.loads((folder / "archive/dataset-v0.4.json").read_text())
    old = json.loads((folder / "archive/dataset-v0.3.json").read_text())
    assert current["rubric_version"] == "python-tracing-v0.4"
    assert Counter(q["difficulty"] for q in current["questions"]) == {
        "easy": 15,
        "medium": 9,
        "hard": 6,
    }
    for q, before in zip(current["questions"], old["questions"], strict=True):
        assert {k: v for k, v in q.items() if k != "rating_evidence"} == before
        trace = Trace(q).run()
        assert trace["event_count"] == q["trace_event_count"]
        assert trace["execution_burden"] == q["dimensions"]["execution_burden"]
        evidence = q["rating_evidence"]
        assert evidence["changing_state"] and evidence["dependency_chain"]
        assert bool(evidence["conceptual_high_pattern"]) == (
            q["dimensions"]["conceptual_interaction"] == "high"
        )
