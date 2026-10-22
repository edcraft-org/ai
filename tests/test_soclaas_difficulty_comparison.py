"""Frozen comparisons, safe resume and failures in the consolidated runner."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluate_difficulty import (
    build_request,
    evaluate,
    frozen_requests,
    index_records,
    load_previous,
    paired_comparison,
    pending_questions,
    reference,
)

ROOT = Path(__file__).resolve().parents[1]


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
    after[0]["reference"] = {"difficulty": "hard"}
    with pytest.raises(ValueError, match="Reference drift"):
        paired_comparison(after, before)


def test_resume_preserves_correct_wrong_and_content_failures():
    questions = [
        {"question_id": name}
        for name in ["correct", "wrong", "invalid", "transport", "unfinished"]
    ]
    records = [
        paired_record("correct", "easy"),
        paired_record("wrong", "medium"),
        paired_record("invalid", None, "JUDGE_INVALID_RESPONSE"),
        paired_record("transport", None, "JUDGE_TRANSPORT"),
    ]
    slots = {(r["question_id"], r["repetition"]): r for r in records}
    assert [
        (q["question_id"], rep) for q, rep in pending_questions(questions, 1, slots)
    ] == [("transport", 1), ("unfinished", 1)]
    assert slots[("wrong", 1)]["prediction"] == "medium"


def test_resume_rejects_changed_requests_settings_and_references(tmp_path):
    question = json.loads(
        (ROOT / "reference_sets/python_tracing/dataset.json").read_text()
    )["questions"][0]
    requests = {question["question_id"]: build_request(question, "RUBRIC")}
    manifest = {
        "requests": frozen_requests(requests),
        "model": "x-test-1",
        "settings": {"generation_max_tokens": 16384},
        "repetitions": 1,
    }
    record = paired_record(question["question_id"], "easy") | {
        "reference": reference(question)
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "records.jsonl").write_text(json.dumps(record) + "\n")
    slots, attempts = load_previous(
        tmp_path,
        [question],
        requests,
        1,
        model="x-test-1",
        settings=manifest["settings"],
    )
    assert len(slots) == len(attempts) == 1
    with pytest.raises(ValueError, match="settings"):
        load_previous(tmp_path, [question], requests, 1, model="x-test-1", settings={})
    with pytest.raises(ValueError, match="Requests"):
        load_previous(
            tmp_path,
            [question],
            {question["question_id"]: build_request(question, "DIFFERENT")},
            1,
        )
    changed = copy.deepcopy(question)
    changed["dimensions"]["execution_burden"] = "unknown"
    with pytest.raises(ValueError, match="Reference"):
        load_previous(tmp_path, [changed], requests, 1)
    with pytest.raises(ValueError, match="Duplicate"):
        index_records([record, record], [question], 1)


def test_resume_uses_flushed_attempt_if_final_records_update_was_interrupted(tmp_path):
    question = json.loads(
        (ROOT / "reference_sets/python_tracing/dataset.json").read_text()
    )["questions"][0]
    requests = {question["question_id"]: build_request(question, "RUBRIC")}
    (tmp_path / "manifest.json").write_text(
        json.dumps({"requests": frozen_requests(requests), "repetitions": 1})
    )
    failed = paired_record(question["question_id"], None, "JUDGE_TRANSPORT") | {
        "reference": reference(question)
    }
    completed = failed | {
        "prediction": "medium",
        "report": {"status": "completed", "error_code": None},
    }
    (tmp_path / "attempts.jsonl").write_text(
        json.dumps(failed) + "\n" + json.dumps(completed) + "\n"
    )
    (tmp_path / "records.jsonl").write_text(json.dumps(failed) + "\n")
    slots, attempts = load_previous(tmp_path, [question], requests, 1)
    assert slots[(question["question_id"], 1)] == completed
    assert len(attempts) == 2
    assert pending_questions([question], 1, slots) == []


async def test_runner_writes_results_without_network_or_overwriting_existing_run(
    tmp_path, monkeypatch
):
    from edcraft_validator.llm.judging import JudgeRun
    from edcraft_validator.llm.usage import ModelUsageSummary
    from scripts import evaluate_difficulty as runner

    class Client:
        def close(self):
            pass

    class Provider:
        raw_response = {"model": "fake"}
        diagnostic = None
        client = Client()

        def __init__(self, **kwargs):
            pass

        def generation_settings(self):
            return {"generation_max_tokens": 16384}

    calls = 0

    async def no_delay(seconds):
        pass

    async def judge(request, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["timeout_seconds"] is None
        return JudgeRun(
            status="error",
            provider="soclaas",
            model="fake",
            prompt_version=request.prompt_version,
            request_sha256="test",
            timeout_seconds=None,
            error_code="JUDGE_TRANSPORT" if calls == 1 else "JUDGE_INVALID_RESPONSE",
            duration_ms=1,
            usage=ModelUsageSummary(),
        )

    monkeypatch.setenv("SOCLAAS_API_KEY", "test")
    monkeypatch.setenv("SOCLAAS_BASE_URL", "http://unused")
    monkeypatch.setattr(runner, "OpenAI", lambda **kwargs: Client())
    monkeypatch.setattr(runner, "EvaluationProvider", Provider)
    monkeypatch.setattr(runner, "run_judge", judge)
    monkeypatch.setattr(runner.asyncio, "sleep", no_delay)
    args = SimpleNamespace(
        model="fake",
        output=tmp_path / "run",
        baseline=None,
        resume=None,
        repetitions=1,
        concurrency=2,
        transport_retries=1,
    )
    result = await evaluate(args)
    assert result["scored"] == 30 and result["correct"] == 0
    assert len((args.output / "records.jsonl").read_text().splitlines()) == 30
    assert (args.output / "predictions.csv").exists()
    assert calls == 31
    assert result["transport_failed_attempts"] == 1
    args.resume = args.output
    args.output = tmp_path / "resumed"
    resumed = await evaluate(args)
    assert calls == 31  # Completed content failures are not sampled again.
    assert resumed["attempts"] == 31 and resumed["scored"] == 30
    with pytest.raises(FileExistsError):
        await evaluate(args)


def test_published_records_reproduce_scores_and_exact_frozen_requests():
    from zipfile import ZipFile

    from scripts.evaluate_difficulty import classification_metrics

    with ZipFile(ROOT / "evidence/issue-86/v0.3-glm-qwen.zip") as archive:
        prefix = "soclaas-v0.3-glm53flash-recovery-r4/"
        glm, qwen = [
            [json.loads(line) for line in archive.read(prefix + name).splitlines()]
            for name in ["records.jsonl", "baseline-records.jsonl"]
        ]
        manifest = json.loads(archive.read(prefix + "baseline-manifest.json"))
    questions = json.loads(
        (ROOT / "reference_sets/python_tracing/dataset.json").read_text()
    )["questions"]
    assert len(index_records(glm, questions, 2)) == 60
    assert len(index_records(qwen, questions, 2)) == 60
    assert classification_metrics(glm)["correct"] == 51
    assert classification_metrics(glm)["scored"] == 54
    assert classification_metrics(qwen)["correct"] == 47
    paired = paired_comparison(glm, qwen)
    assert paired["paired_slots"] == 54
    assert paired["both_correct"] == 41
    assert paired["candidate_only_correct"] == 10
    assert paired["qwen_only_correct"] == 2
    rubric = (ROOT / "docs/difficulty-rubric-v0.3.md").read_text()
    requests = {q["question_id"]: build_request(q, rubric) for q in questions}
    assert frozen_requests(requests) == manifest["requests"]
