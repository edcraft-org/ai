"""Frozen split, failure denominators and durable review records, without APIs."""

import asyncio
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from edcraft_validator.application import code_difficulty
from scripts import evaluate_code_relevance as evaluation
from tests.test_code_relevance import Decisions


def test_plan_keeps_held_out_content_fixed_and_reference_labels_hidden():
    data = json.loads(evaluation.DATASET.read_text())
    controls = json.loads(evaluation.CONTROLS.read_text())
    cases = evaluation.evaluation_cases(data, controls)
    held_out = [c for c in cases if c["group"] == "held_out"]
    assert len(held_out) == 12 and len(cases) == 19
    originals = {q["question_id"]: q for q in data["questions"]}
    for case in held_out:
        original = originals[case["case_id"]]
        assert original["split"] == "held_out" and case["expected"] is None
        assert all(original[k] == v for k, v in case["question"].items())
        assert not {"difficulty", "dimensions", "solution", "difficulty_reason"} & set(
            case["question"]
        )
    assert {c["case_id"] for c in cases if c["group"] == "control"} == {
        f"quality-control-{name}"
        for name in (
            "relevant",
            "off-topic",
            "omitted-requirement",
            "topic-words-missing-concept",
            "ambiguous",
            "wrong-answer",
            "duplicate-distractor",
        )
    }
    duplicate = controls | {"cases": controls["cases"] * 2}
    with pytest.raises(ValueError, match="unique"):
        evaluation.evaluation_cases(data, duplicate)


async def test_evaluator_freezes_settings_flushes_failures_and_retains_disagreement(
    monkeypatch, tmp_path
):
    class PartialDecisions(Decisions):
        calls = 0

        def score(self, request_text, question_text):
            type(self).calls += 1
            if self.calls == 1:
                raise RuntimeError("PRIVATE REMOTE ERROR")
            return super().score(request_text, question_text)

    def forbidden(*args, **kwargs):
        pytest.fail("Relevance evaluation must not start another judge call")

    monkeypatch.setattr(code_difficulty, "run_judge", forbidden)
    monkeypatch.setattr(evaluation, "QwenDecisionProvider", PartialDecisions)
    before = evaluation.DATASET.read_bytes()
    output = tmp_path / "review.jsonl"
    result = await evaluation.evaluate(output)
    assert result["recorded"] == 19 and result["unresolved"] == 0
    assert result["statuses"] == {"error": 1, "assessed": 18}
    assert result["new_judge_calls"] == 0
    assert result["protocol_failure_count"] == 0
    assert result["mandatory_check_failure_count"] == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 19
    assert "PRIVATE REMOTE ERROR" not in output.read_text()
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert len(manifest["cases"]) == 19 and manifest["source_revision"]
    assert manifest["cases"] == evaluation.evaluation_cases(
        json.loads(before), json.loads(evaluation.CONTROLS.read_text())
    )
    assert "judge" not in manifest and manifest["new_judge_calls"] == 0
    assert manifest["protocol"] == "code-relevance-evaluation-v5-decision"
    assert "difficulty_report_sha256" not in manifest
    assert result == json.loads(output.with_suffix(".summary.json").read_text())
    assert evaluation.DATASET.read_bytes() == before
    assert result["groups"]["held_out"]["technical"] == {"passed": 12}
    assert result["groups"]["control"]["technical"] == {"passed": 5, "failed": 2}
    assert not result["groups"]["control"]["control_disagreements"]
    assert all("difficulty_quality" not in r["report"] for r in records)
    assert all("judge" not in r["report"] for r in records)
    wrong = next(r for r in records if r["case_id"] == "quality-control-wrong-answer")
    wrong["report"]["technical"]["status"] = "passed"
    assert (
        evaluation.summary(records, 19)["deterministic_control_disagreement_count"] == 1
    )
    assert evaluation.summary(records, 19)["mandatory_check_failure_count"] == 1
    with pytest.raises(FileExistsError):
        await evaluation.evaluate(output)


def test_removed_difficulty_report_cli_option_fails_before_evaluation(
    monkeypatch, tmp_path
):
    def forbidden(*args, **kwargs):
        pytest.fail("Obsolete options must be rejected before evaluation starts")

    monkeypatch.setattr(evaluation, "evaluate", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review",
            "--output",
            str(tmp_path / "review.jsonl"),
            "--difficulty-reports",
            str(tmp_path / "old-difficulty.jsonl"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        evaluation.main()
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


def test_empty_summary_counts_all_requested_cases_as_unresolved():
    result = evaluation.summary([], 19)
    assert result["unresolved"] == 19 and result["recorded"] == 0
    assert result["groups"]["held_out"]["score_range"] is None
    assert result["median_duration_ms"] is None


def test_concurrent_run_cannot_replace_the_winning_manifest(monkeypatch, tmp_path):
    checked = threading.Barrier(2)
    reserved = threading.Event()
    local = threading.local()
    output = tmp_path / "review.jsonl"
    original_open = Path.open

    class RacingDecisions(Decisions):
        def __init__(self):
            super().__init__()
            self.model = local.name
            if not getattr(local, "client_created", False):
                local.client_created = True
                checked.wait(timeout=10)
                if self.model == "second-run":
                    assert reserved.wait(timeout=10)

    def observed_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == output and mode == "x":
            reserved.set()
        return stream

    def invoke(name):
        local.name = name
        return asyncio.run(evaluation.evaluate(output))

    monkeypatch.setattr(evaluation, "QwenDecisionProvider", RacingDecisions)
    monkeypatch.setattr(Path, "open", observed_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, "first-run")
        second = pool.submit(invoke, "second-run")
        with pytest.raises(FileExistsError):
            second.result(timeout=20)
        assert first.result(timeout=20)["recorded"] == 19
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert manifest["decision"]["model"] == "first-run"
    assert {r["report"]["relevance"]["decision"]["model"] for r in records} == {
        "first-run"
    }
    assert json.loads(output.with_suffix(".summary.json").read_text())["recorded"] == 19


@pytest.mark.parametrize(
    "occupied_suffix", [".jsonl", ".manifest.json", ".summary.json"]
)
async def test_output_collision_preserves_existing_files_and_rolls_back_reservations(
    monkeypatch, tmp_path, occupied_suffix
):
    output = tmp_path / "review.jsonl"
    existing = output.with_suffix(occupied_suffix)
    existing.write_bytes(b"prior evaluation evidence\n")
    monkeypatch.setattr(evaluation, "QwenDecisionProvider", Decisions)
    with pytest.raises(FileExistsError):
        await evaluation.evaluate(output)
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_bytes() == b"prior evaluation evidence\n"


@pytest.mark.parametrize(
    "section,status",
    [
        (None, None),
        ("technical", "error"),
        ("technical", "failed"),
        ("requirements", "unknown"),
        ("requirements", "missing"),
    ],
)
def test_cli_checks_held_out_measurements_and_preserves_expected_control_failures(
    monkeypatch, tmp_path, section, status
):
    original_assess = evaluation.review_code_question_relevance
    cases = evaluation.evaluation_cases(
        json.loads(evaluation.DATASET.read_text()),
        json.loads(evaluation.CONTROLS.read_text()),
    )
    selected = evaluation.CodeDifficultyQuestion.model_validate(cases[0]["question"])

    async def assess(question, request, **kwargs):
        report = await original_assess(question, request, **kwargs)
        if section is not None and question.sha256 == selected.sha256:
            getattr(report, section).status = status
        return report

    output = tmp_path / "review.jsonl"
    monkeypatch.setattr(evaluation, "QwenDecisionProvider", Decisions)
    monkeypatch.setattr(evaluation, "review_code_question_relevance", assess)
    monkeypatch.setattr(sys, "argv", ["review", "--output", str(output)])
    assert evaluation.main() == (0 if section is None else 2)
    result = json.loads(output.with_suffix(".summary.json").read_text())
    assert result["recorded"] == 19 and result["statuses"] == {"assessed": 19}
    assert result["groups"]["control"]["technical"] == {"passed": 5, "failed": 2}
    assert result["mandatory_check_failure_count"] == (0 if section is None else 1)
    assert result["deterministic_control_disagreement_count"] == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    selected_record = next(r for r in records if r["case_id"] == cases[0]["case_id"])
    if section is not None:
        assert selected_record["report"][section]["status"] == status


def test_controls_are_versioned_separately_from_frozen_dataset():
    controls = json.loads(Path(evaluation.CONTROLS).read_text())
    assert controls["version"] == "code-quality-controls-v1"
    assert "not human quality reference labels" in controls["notes"]
