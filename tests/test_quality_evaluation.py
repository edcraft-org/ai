"""Frozen split, failure denominators and durable review records, without APIs."""

import json
from pathlib import Path

import pytest

from edcraft_validator.application import code_difficulty
from scripts import evaluate_code_quality as evaluation
from tests.test_code_quality import Embeddings
from tests.test_difficulty_tool import Provider, question


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
    class PartialEmbeddings(Embeddings):
        calls = 0

        def embed(self, texts):
            type(self).calls += 1
            if self.calls == 1:
                raise RuntimeError("PRIVATE REMOTE ERROR")
            return super().embed(texts)

    provider = Provider()
    previous = await code_difficulty.assess_code_question_difficulty(
        question(), provider_factory=lambda: provider
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Relevance evaluation must not start another judge call")

    monkeypatch.setattr(code_difficulty, "run_judge", forbidden)
    monkeypatch.setattr(evaluation, "OpenAIEmbeddingProvider", PartialEmbeddings)
    before = evaluation.DATASET.read_bytes()
    output = tmp_path / "review.jsonl"
    result = await evaluation.evaluate(
        output, difficulty_reports={previous.question_sha256: previous}
    )
    assert result["recorded"] == 19 and result["unresolved"] == 0
    assert result["statuses"] == {"error": 1, "assessed": 18}
    assert result["new_judge_calls"] == 0 and len(provider.requests) == 1
    assert result["protocol_failure_count"] == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 19
    assert "PRIVATE REMOTE ERROR" not in output.read_text()
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert len(manifest["cases"]) == 19 and manifest["dataset_sha256"]
    assert "judge" not in manifest and manifest["new_judge_calls"] == 0
    assert manifest["difficulty_report_sha256"][previous.question_sha256]
    assert result == json.loads(output.with_suffix(".summary.json").read_text())
    assert evaluation.DATASET.read_bytes() == before
    assert result["groups"]["held_out"]["technical"] == {"passed": 12}
    assert result["groups"]["control"]["technical"] == {"passed": 5, "failed": 2}
    assert not result["groups"]["control"]["control_disagreements"]
    assert result["groups"]["control"]["difficulty_quality"] == {
        "reused": 3,
        "not_supplied": 4,
    }
    assert all("judge" not in r["report"] for r in records)
    wrong = next(r for r in records if r["case_id"] == "quality-control-wrong-answer")
    wrong["report"]["technical"]["status"] = "passed"
    assert (
        evaluation.summary(records, 19)["deterministic_control_disagreement_count"] == 1
    )
    with pytest.raises(FileExistsError):
        await evaluation.evaluate(output)


async def test_invalid_reused_report_fails_before_creating_embedding_client(
    monkeypatch, tmp_path
):
    report = await code_difficulty.assess_code_question_difficulty(
        question(), provider_factory=Provider
    )
    report.judge.assessment.option_evidence.pop()

    def forbidden():
        pytest.fail("Invalid existing evidence must fail before creating a client")

    monkeypatch.setattr(evaluation, "OpenAIEmbeddingProvider", forbidden)
    with pytest.raises(ValueError, match="cover the supplied options"):
        await evaluation.evaluate(
            tmp_path / "invalid.jsonl",
            difficulty_reports={report.question_sha256: report},
        )
    assert not list(tmp_path.iterdir())


async def test_existing_difficulty_report_loader_rejects_duplicates(tmp_path):
    report = await code_difficulty.assess_code_question_difficulty(
        question(), provider_factory=Provider
    )
    path = tmp_path / "difficulty.jsonl"
    path.write_text(report.model_dump_json() + "\n")
    assert evaluation.load_difficulty_reports(path) == {report.question_sha256: report}
    path.write_text((report.model_dump_json() + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate question hash"):
        evaluation.load_difficulty_reports(path)


def test_empty_summary_counts_all_requested_cases_as_unresolved():
    result = evaluation.summary([], 19)
    assert result["unresolved"] == 19 and result["recorded"] == 0
    assert result["groups"]["held_out"]["similarity_range"] is None
    assert result["median_duration_ms"] is None


def test_controls_are_versioned_separately_from_frozen_dataset():
    controls = json.loads(Path(evaluation.CONTROLS).read_text())
    assert controls["version"] == "code-quality-controls-v1"
    assert "not human quality reference labels" in controls["notes"]
