"""Guard the exact-baseline comparison and transport-aware paired statistics."""

import copy
import json
from pathlib import Path

import pytest

from scripts.compare_soclaas_difficulty import (
    attempt_plan,
    paired_comparison,
    validate_frozen_requests,
)
from scripts.evaluate_trace_difficulty import build_request, digest

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_request_validation_detects_label_rubric_schema_and_message_drift():
    dataset = (ROOT / "reference_sets/python_tracing/dataset.json").read_bytes()
    rubric = (ROOT / "docs/difficulty-rubric-v0.3.md").read_bytes()
    assert json.loads(dataset)["rubric_version"] == "python-tracing-v0.3"
    assert (
        dataset
        == (
            ROOT / "reference_sets/python_tracing/archive/dataset-v0.3.json"
        ).read_bytes()
    )
    questions = json.loads(dataset)["questions"]
    frozen = {}
    for q in questions:
        r = build_request(q, rubric.decode())
        frozen[q["question_id"]] = {
            "messages": r.messages,
            "schema": r.response_model.model_json_schema(),
            "prompt_version": r.prompt_version,
            "schema_name": r.schema_name,
        }
    baseline = {
        "dataset_sha256": digest(dataset),
        "rubric_sha256": digest(rubric),
        "requests": frozen,
    }
    assert len(validate_frozen_requests(dataset, rubric, baseline)[1]) == 30
    with pytest.raises(ValueError, match="Dataset"):
        validate_frozen_requests(dataset + b" ", rubric, baseline)
    with pytest.raises(ValueError, match="Rubric"):
        validate_frozen_requests(dataset, rubric + b" ", baseline)
    for key in ["schema", "messages"]:
        altered = copy.deepcopy(baseline)
        altered["requests"][questions[0]["question_id"]][key] = {}
        with pytest.raises(ValueError, match="Request"):
            validate_frozen_requests(dataset, rubric, altered)


def paired_record(question_id, prediction, error=None):
    return {
        "question_id": question_id,
        "repetition": 1,
        "reference": {"difficulty": "easy"},
        "prediction": prediction,
        "report": {"status": "error" if error else "completed", "error_code": error},
    }


def test_paired_comparison_excludes_transport_but_keeps_content_failures():
    before = [
        paired_record("a", "medium"),
        paired_record("b", "easy"),
        paired_record("c", "easy"),
    ]
    after = [
        paired_record("a", "easy"),
        paired_record("b", None, "JUDGE_SCHEMA_VALIDATION"),
        paired_record("c", None, "JUDGE_TRANSPORT"),
    ]
    result = paired_comparison(after, before)
    assert result["paired_slots"] == 2
    assert result["candidate_only_correct"] == 1
    assert result["qwen_only_correct"] == 1
    assert len(result["changes"]) == 2
    after[0]["reference"] = {"difficulty": "hard"}
    with pytest.raises(ValueError, match="Reference drift"):
        paired_comparison(after, before)


def test_recovery_preserves_completed_results_and_tracks_transport_separately():
    correct = paired_record("correct", "easy") | {"attempt": 1}
    wrong = paired_record("wrong", "medium") | {"attempt": 1}
    invalid = paired_record("invalid", None, "JUDGE_SCHEMA_VALIDATION") | {"attempt": 1}
    failed = paired_record("failed", None, "JUDGE_TRANSPORT") | {"attempt": 1}
    history = [correct, wrong, invalid, failed]
    slots = {(r["question_id"], r["repetition"]): r for r in history}
    interrupted = [{"question_id": "interrupted", "repetition": 1, "attempt": 1}]
    for q in ["correct", "wrong", "invalid"]:
        assert attempt_plan(q, 1, slots, history, interrupted) == []
    assert attempt_plan("failed", 1, slots, history, interrupted) == [2]
    assert attempt_plan("interrupted", 1, slots, history, interrupted) == [2, 3]
    assert attempt_plan("queued", 1, slots, history, interrupted) == [1, 2]
    assert slots[("wrong", 1)] is wrong


def test_outage_recovery_extends_transport_budget_without_rerunning_predictions():
    failed = paired_record("failed", None, "JUDGE_TRANSPORT") | {"attempt": 1}
    again = failed | {"attempt": 2}
    slots = {("failed", 1): again}
    assert attempt_plan("failed", 1, slots, [failed, again], []) == []
    assert attempt_plan("failed", 1, slots, [failed, again], [], 1) == [3]
    completed = paired_record("failed", "medium") | {"attempt": 3}
    slots[("failed", 1)] = completed
    assert attempt_plan("failed", 1, slots, [failed, again, completed], [], 1) == []
