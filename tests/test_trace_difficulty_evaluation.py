"""Reference integrity, label blinding and failure-aware evaluation statistics."""

import json
from collections import Counter
from pathlib import Path

from scripts.difficulty_trace import Trace
from scripts.evaluate_trace_difficulty import (
    DIMENSIONS,
    build_request,
    derived_level,
    metrics,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "reference_sets/python_tracing/archive/dataset-v0.3.json"


def test_reference_content_is_preserved_and_every_trace_matches_approved_counts():
    dataset = json.loads(DATASET.read_text())
    old = json.loads((DATASET.parent / "dataset-v0.2.json").read_text())
    assert dataset["rubric_version"] == "python-tracing-v0.3"
    assert Counter(q["difficulty"] for q in dataset["questions"]) == {
        "easy": 15,
        "medium": 9,
        "hard": 6,
    }
    for question, baseline in zip(dataset["questions"], old["questions"], strict=True):
        for key in (
            "question_id",
            "code",
            "entry_function",
            "inputs",
            "question",
            "answer_target",
            "options",
            "correct_option",
            "topic",
            "split",
            "solution",
        ):
            assert question[key] == baseline[key]
        trace = Trace(question).run()
        assert trace["event_count"] == question["trace_event_count"]
        assert trace["execution_burden"] == question["dimensions"]["execution_burden"]
        assert set(question["dimensions"]) == set(DIMENSIONS)
        assert (
            derived_level(
                {
                    key: {"rating": value}
                    for key, value in question["dimensions"].items()
                }
            )
            == question["difficulty"]
        )


def test_model_request_excludes_all_reference_metadata_and_schema_is_closed():
    question = json.loads(DATASET.read_text())["questions"][0]
    question = question | {
        "difficulty_reason": "SECRET_REFERENCE",
        "trace_event_count": 999999,
    }
    request = build_request(question, "RUBRIC_RULES_ONLY")
    body = json.loads(request.messages[1]["content"])["question"]
    assert set(body) == {
        "code",
        "entry_function",
        "inputs",
        "question",
        "answer_target",
        "options",
        "correct_option",
    }
    assert "SECRET_REFERENCE" not in str(request.messages)
    assert "999999" not in str(request.messages)
    schema = request.response_model.model_json_schema()
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def record(reference, prediction, *, error=False):
    return {
        "reference": {
            "difficulty": reference,
            "dimensions": dict.fromkeys(DIMENSIONS, "low"),
            "trace_event_count": 3,
        },
        "prediction": prediction,
        "dimension_predictions": {} if error else dict.fromkeys(DIMENSIONS, "low"),
        "predicted_event_count": None if error else 3,
        "consistency_findings": [],
        "report": {
            "status": "error" if error else "completed",
            "error_code": "JUDGE_TIMEOUT" if error else None,
        },
    }


def test_errors_and_unrecorded_jobs_are_nonmatches_and_empty_metrics_are_unknown():
    result = metrics([record("easy", "easy"), record("hard", None, error=True)], 3)
    assert result["accuracy_all_requested"] == 1 / 3
    assert result["accuracy_valid_only"] == 1
    assert result["unresolved"] == 1
    assert result["classes"]["hard"]["recall"] == 0
    assert result["unknown_or_failed_by_reference"] == {"hard": 1}
    assert result["dimensions"]["changing_state"]["accuracy"] == 1 / 3
    assert metrics([], 0)["accuracy_all_requested"] is None


def test_overall_rule_does_not_promote_burden_or_state_to_hard():
    values = {key: {"rating": "low"} for key in DIMENSIONS}
    assert derived_level(values) == "easy"
    values["execution_burden"]["rating"] = "high"
    values["changing_state"]["rating"] = "high"
    assert derived_level(values) == "medium"
    values["conceptual_interaction"]["rating"] = "high"
    assert derived_level(values) == "hard"
    values["changing_state"]["rating"] = "unknown"
    assert derived_level(values) is None
