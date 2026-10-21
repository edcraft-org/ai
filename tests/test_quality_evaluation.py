"""Frozen split, failure denominators and durable review records, without APIs."""

import json
from pathlib import Path

import pytest

from scripts import evaluate_code_quality as evaluation
from tests.test_code_quality import Embeddings, Judge


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

    class FixedJudge(Judge):
        def generation_settings(self):
            return {"max_retries": 0, "response_format": "json_schema"}

    monkeypatch.setattr(evaluation, "configured_quality_provider", FixedJudge)
    monkeypatch.setattr(evaluation, "OpenAIEmbeddingProvider", PartialEmbeddings)
    before = evaluation.DATASET.read_bytes()
    output = tmp_path / "review.jsonl"
    result = await evaluation.evaluate(output)
    assert result["recorded"] == 19 and result["unresolved"] == 0
    assert result["statuses"] == {"partial": 1, "assessed": 18}
    assert result["protocol_failure_count"] == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 19
    assert "PRIVATE REMOTE ERROR" not in output.read_text()
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert len(manifest["cases"]) == 19 and manifest["dataset_sha256"]
    assert manifest["judge"]["settings"] == FixedJudge().generation_settings()
    assert result == json.loads(output.with_suffix(".summary.json").read_text())
    assert evaluation.DATASET.read_bytes() == before
    assert result["groups"]["held_out"]["technical"] == {"passed": 12}
    assert result["groups"]["held_out"]["distractor_plausibility"] == {"good": 36}
    assert result["groups"]["control"]["technical"] == {"passed": 5, "failed": 2}
    assert result["groups"]["control"]["control_disagreements"]
    assert records[0]["report"]["judge"]["assessment"]["uncertainty"]
    with pytest.raises(FileExistsError):
        await evaluation.evaluate(output)


def test_empty_summary_counts_all_requested_cases_as_unresolved():
    result = evaluation.summary([], 19)
    assert result["unresolved"] == 19 and result["recorded"] == 0
    assert result["groups"]["held_out"]["similarity_range"] is None
    assert result["median_duration_ms"] is None


def test_controls_are_versioned_separately_from_frozen_dataset():
    controls = json.loads(Path(evaluation.CONTROLS).read_text())
    assert controls["version"] == "code-quality-controls-v1"
    assert "not human quality reference labels" in controls["notes"]
