"""Freeze a quality review plan before judging the reserved MCQs and controls."""

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from edcraft_validator.application.code_quality import assess_code_question_quality
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.quality import QualityRequest
from edcraft_validator.llm.embeddings import OpenAIEmbeddingProvider
from edcraft_validator.mcp.quality_tools import configured_quality_provider

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "reference_sets/python_tracing/dataset.json"
CONTROLS = ROOT / "reference_sets/python_tracing/quality-controls.json"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def evaluation_cases(dataset: dict, controls: dict) -> list[dict]:
    cases = []
    for raw in dataset["questions"]:
        if raw["split"] != "held_out":
            continue
        question = CodeDifficultyQuestion.model_validate(
            {name: raw[name] for name in CodeDifficultyQuestion.model_fields}
        )
        cases.append(
            {
                "case_id": raw["question_id"],
                "group": "held_out",
                "question": question.model_dump(mode="json"),
                "request": QualityRequest(
                    prompt=f"Create a Python tracing MCQ about {raw['topic']}.",
                    answer_target=raw["answer_target"],
                    num_distractors=len(raw["options"]) - 1,
                    learner_prerequisites=["Understands the Python semantics shown."],
                ).model_dump(mode="json"),
                "expected": None,
            }
        )
    cases.extend(controls["cases"])
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case IDs must be unique")
    # Validate the entire frozen plan before making any external calls.
    for case in cases:
        CodeDifficultyQuestion.model_validate(case["question"])
        QualityRequest.model_validate(case["request"])
    return cases


def summary(records: list[dict], requested: int) -> dict:
    groups = {}
    for group in ("held_out", "control"):
        selected = [r for r in records if r["group"] == group]
        ratings = {
            name: Counter() for name in ("relevance", "clarity", "answerability")
        }
        disagreements = []
        distractor_ratings = Counter()
        uncertainty_cases = []
        for record in selected:
            report = record["report"]
            assessment = report["judge"]["assessment"]
            if assessment:
                # The designation is recorded in the frozen manifest, not inferred
                # from the judge's opinions about the options.
                correct = record["correct_option"]
                distractor_ratings.update(
                    item["rating"]
                    for key, item in assessment["option_evidence"].items()
                    if key != correct
                )
                if assessment["uncertainty"]:
                    uncertainty_cases.append(record["case_id"])
            for name in ratings:
                ratings[name][
                    assessment[name]["rating"] if assessment else "error"
                ] += 1
            expected = record["expected"] or {}
            observed = {
                "technical": report["technical"]["status"],
                "requirements": report["requirements"]["status"],
                **{
                    name: assessment[name]["rating"] if assessment else "error"
                    for name in ratings
                },
            }
            mismatches = {
                name: {"expected": value, "observed": observed[name]}
                for name, value in expected.items()
                if observed[name] != value
            }
            if mismatches:
                disagreements.append(
                    {"case_id": record["case_id"], "fields": mismatches}
                )
        similarities = [
            r["report"]["similarity"]["similarity"]
            for r in selected
            if r["report"]["similarity"]["status"] == "measured"
        ]
        groups[group] = {
            "recorded": len(selected),
            "ratings": ratings,
            "technical": Counter(r["report"]["technical"]["status"] for r in selected),
            "requirements": Counter(
                r["report"]["requirements"]["status"] for r in selected
            ),
            "similarity_range": [min(similarities), max(similarities)]
            if similarities
            else None,
            "control_disagreements": disagreements,
            "distractor_plausibility": distractor_ratings,
            "uncertainty_cases": uncertainty_cases,
        }
    times = [r["report"]["duration_ms"] for r in records]
    judge_inputs = [r["report"]["judge"]["usage"]["input_tokens"] for r in records]
    judge_outputs = [r["report"]["judge"]["usage"]["output_tokens"] for r in records]
    embedding_inputs = [
        r["report"]["similarity"]["usage"]["input_tokens"] for r in records
    ]

    def complete_total(counts):
        return sum(counts) if all(v is not None for v in counts) else None

    return {
        "requested": requested,
        "recorded": len(records),
        "unresolved": requested - len(records),
        "groups": groups,
        "statuses": Counter(r["report"]["status"] for r in records),
        "protocol_failure_count": sum(
            bool(r.get("protocol_findings")) for r in records
        ),
        "judge_input_tokens": complete_total(judge_inputs),
        "judge_output_tokens": complete_total(judge_outputs),
        "embedding_input_tokens": complete_total(embedding_inputs),
        "median_duration_ms": statistics.median(times) if times else None,
        "limitations": [
            "No human relevance or quality labels exist for the held-out set; "
            "these are descriptive reviews, not quality accuracy.",
            "Control expectations are authored engineering hypotheses, "
            "not independent human calibration.",
            "Single judge, one call per case; uncertainty and all option "
            "evidence remain in JSONL.",
            "No similarity cutoff, no aggregate pass score and no learner calibration.",
            "Provider model IDs do not establish immutable model weights "
            "or reproducible sampling.",
        ],
    }


async def evaluate(output: Path) -> dict:
    cases = evaluation_cases(
        json.loads(DATASET.read_text()), json.loads(CONTROLS.read_text())
    )
    # Construct once for settings only, never reuse mutable per-call providers.
    judge = configured_quality_provider()
    embedding = OpenAIEmbeddingProvider()
    settings = judge.generation_settings()
    if settings["max_retries"] != 0:
        raise ValueError("Set SOCLAAS_MAX_RETRIES=0 for this single-call review")
    if settings["response_format"] != "json_schema":
        raise ValueError(
            "Set SOCLAAS_RESPONSE_FORMAT=json_schema for the frozen review"
        )
    source_files = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__)]
    source_hash = sha256(
        b"".join(
            str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes()
            for p in source_files
        )
    )
    manifest = {
        "protocol": "code-quality-evaluation-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": source_hash,
        "dataset_sha256": sha256(DATASET.read_bytes()),
        "controls_sha256": sha256(CONTROLS.read_bytes()),
        "judge": {
            "provider": judge.provider,
            "model": judge.model,
            "settings": settings,
        },
        "embedding": {
            "provider": embedding.provider,
            "model": embedding.model,
            "model_version": embedding.model_version,
            "max_retries": 0,
            "transport_timeout_seconds": 30,
        },
        "judge_deadline_seconds": 120,
        "embedding_deadline_seconds": 35,
        "execution_timeout_seconds": 2,
        "concurrency": 2,
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(".manifest.json")
    summary_path = output.with_suffix(".summary.json")
    # Refuse to overwrite an earlier review, even a partial one.
    if any(p.exists() for p in (output, manifest_path, summary_path)):
        raise FileExistsError("choose a fresh evaluation output path")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    records = []
    semaphore = asyncio.Semaphore(2)
    with output.open("x") as stream:

        async def run(case):
            async with semaphore:
                report = await assess_code_question_quality(
                    CodeDifficultyQuestion.model_validate(case["question"]),
                    QualityRequest.model_validate(case["request"]),
                    provider_factory=configured_quality_provider,
                    embedding_provider_factory=OpenAIEmbeddingProvider,
                    judge_timeout_seconds=120,
                )
                protocol_findings = []
                if report.judge.model is not None and (
                    report.judge.provider_settings != settings
                    or report.judge.model != judge.model
                ):
                    protocol_findings.append("JUDGE_SETTINGS_DRIFT")
                if report.similarity.model is not None and (
                    report.similarity.model != embedding.model
                ):
                    protocol_findings.append("EMBEDDING_MODEL_DRIFT")
                record = {
                    "case_id": case["case_id"],
                    "group": case["group"],
                    "expected": case["expected"],
                    "correct_option": case["question"]["correct_option"],
                    "protocol_findings": protocol_findings,
                    "report": report.model_dump(mode="json"),
                }
                stream.write(json.dumps(record, allow_nan=False) + "\n")
                stream.flush()
                records.append(record)
                summary_path.write_text(
                    json.dumps(summary(records, len(cases)), indent=2) + "\n"
                )
                print(
                    f"{len(records)}/{len(cases)} {case['case_id']}: {report.status}",
                    flush=True,
                )

        try:
            await asyncio.gather(*(run(case) for case in cases))
        finally:
            result = summary(records, len(cases))
            summary_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    # Environment values are captured in the manifest; no adaptive tuning.
    os.environ.setdefault("SOCLAAS_MAX_RETRIES", "0")
    result = asyncio.run(evaluate(args.output))
    return (
        0
        if result["statuses"].get("assessed", 0) == result["requested"]
        and not result["protocol_failure_count"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
