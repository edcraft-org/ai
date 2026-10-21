"""Freeze an embedding relevance review; never start a generative judge call."""

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

from edcraft_validator.application.code_difficulty import CodeDifficultyReport
from edcraft_validator.application.code_quality import (
    assess_code_question_quality,
    reuse_difficulty_quality,
)
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.quality import QualityRequest
from edcraft_validator.llm.embeddings import OpenAIEmbeddingProvider

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "reference_sets/python_tracing/dataset.json"
CONTROLS = ROOT / "reference_sets/python_tracing/quality-controls.json"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@contextmanager
def reserve_outputs(paths: tuple[Path, ...]) -> Iterator[list[TextIO]]:
    """Own every output before writing; roll back only an incomplete reservation."""
    with ExitStack() as stack:
        streams = []
        try:
            for path in paths:
                streams.append(stack.enter_context(path.open("x", encoding="utf-8")))
        except OSError:
            stack.close()
            for path in paths[: len(streams)]:
                path.unlink()
            raise
        yield streams


def write_summary(stream: TextIO, result: dict) -> None:
    stream.seek(0)
    stream.write(json.dumps(result, indent=2) + "\n")
    stream.truncate()
    stream.flush()


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
    # Preserve the frozen control content. Only deterministic expectations are
    # scored by v2; historical rubric expectations remain in the control source.
    cases.extend(
        {
            **case,
            "expected": {
                key: value
                for key, value in case["expected"].items()
                if key in {"technical", "requirements"}
            },
        }
        for case in controls["cases"]
    )
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case IDs must be unique")
    # Validate the entire frozen plan before making any external calls.
    for case in cases:
        CodeDifficultyQuestion.model_validate(case["question"])
        QualityRequest.model_validate(case["request"])
    return cases


def load_difficulty_reports(path: Path) -> dict[str, CodeDifficultyReport]:
    """Load existing standalone concrete-MCQ reports, without any inference."""
    reports = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        report = CodeDifficultyReport.model_validate_json(line, strict=True)
        if report.question_sha256 in reports:
            raise ValueError("duplicate question hash in difficulty reports")
        reports[report.question_sha256] = report
    return reports


def summary(records: list[dict], requested: int) -> dict:
    groups = {}
    for group in ("held_out", "control"):
        selected = [r for r in records if r["group"] == group]
        disagreements = []
        for record in selected:
            observed = {
                name: record["report"][name]["status"]
                for name in ("technical", "requirements")
            }
            mismatches = {
                name: {"expected": value, "observed": observed[name]}
                for name, value in (record["expected"] or {}).items()
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
            "technical": Counter(r["report"]["technical"]["status"] for r in selected),
            "requirements": Counter(
                r["report"]["requirements"]["status"] for r in selected
            ),
            "difficulty_quality": Counter(
                r["report"]["difficulty_quality"]["status"] for r in selected
            ),
            "similarity_range": [min(similarities), max(similarities)]
            if similarities
            else None,
            "control_disagreements": disagreements,
        }
    times = [r["report"]["duration_ms"] for r in records]
    tokens = [r["report"]["similarity"]["usage"]["input_tokens"] for r in records]
    return {
        "requested": requested,
        "recorded": len(records),
        "unresolved": requested - len(records),
        "groups": groups,
        "deterministic_control_disagreement_count": len(
            groups["control"]["control_disagreements"]
        ),
        "mandatory_check_failure_count": sum(
            any(
                record["report"][name]["status"]
                != (record["expected"] or {}).get(name, expected_status)
                for name, expected_status in (
                    ("technical", "passed"),
                    ("requirements", "satisfied"),
                )
            )
            for record in records
        ),
        "statuses": Counter(r["report"]["status"] for r in records),
        "protocol_failure_count": sum(
            bool(r.get("protocol_findings")) for r in records
        ),
        "new_judge_calls": 0,
        "embedding_input_tokens": sum(tokens)
        if all(v is not None for v in tokens)
        else None,
        "median_duration_ms": statistics.median(times) if times else None,
        "limitations": [
            "Embedding similarity is advisory, with no pass cutoff "
            "or verified semantic alignment.",
            "No relevance rubric is judged. Ambiguity and missing concepts "
            "can escape these checks.",
            "Existing difficulty evidence is optional, question-specific "
            "and not a request-alignment judgment.",
            "Reused judge usage describes prior calls, "
            "excluded from this run's new usage.",
            "The held-out set has no human relevance labels; "
            "no relevance accuracy is claimed.",
            "Provider model IDs do not establish immutable model weights.",
        ],
    }


async def evaluate(
    output: Path, *, difficulty_reports: dict[str, CodeDifficultyReport] | None = None
) -> dict:
    cases = evaluation_cases(
        json.loads(DATASET.read_text()), json.loads(CONTROLS.read_text())
    )
    difficulty_reports = difficulty_reports or {}
    questions = [CodeDifficultyQuestion.model_validate(c["question"]) for c in cases]
    planned_questions = {question.sha256: question for question in questions}
    if not difficulty_reports.keys() <= planned_questions.keys():
        raise ValueError("difficulty reports contain questions outside this plan")
    # Validate every reused report before creating a client or starting a case.
    for question_hash, report in difficulty_reports.items():
        reuse_difficulty_quality(planned_questions[question_hash], report)
    manifest_path = output.with_suffix(".manifest.json")
    summary_path = output.with_suffix(".summary.json")
    embedding = OpenAIEmbeddingProvider()
    source_files = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__)]
    manifest = {
        "protocol": "code-quality-evaluation-v2-no-extra-judge",
        "created_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": sha256(
            b"".join(
                str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes()
                for p in source_files
            )
        ),
        "dataset_sha256": sha256(DATASET.read_bytes()),
        "controls_sha256": sha256(CONTROLS.read_bytes()),
        "embedding": {
            "provider": embedding.provider,
            "model": embedding.model,
            "model_version": embedding.model_version,
            "max_retries": 0,
            "transport_timeout_seconds": 30,
        },
        "new_judge_calls": 0,
        "difficulty_report_sha256": {
            key: sha256(report.model_dump_json().encode())
            for key, report in difficulty_reports.items()
        },
        "embedding_deadline_seconds": 35,
        "execution_timeout_seconds": 2,
        "concurrency": 2,
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    semaphore = asyncio.Semaphore(2)
    with reserve_outputs((output, manifest_path, summary_path)) as (
        stream,
        manifest_stream,
        summary_stream,
    ):
        manifest_stream.write(json.dumps(manifest, indent=2) + "\n")
        manifest_stream.flush()

        async def run(case):
            async with semaphore:
                question = CodeDifficultyQuestion.model_validate(case["question"])
                report = await assess_code_question_quality(
                    question,
                    QualityRequest.model_validate(case["request"]),
                    embedding_provider_factory=OpenAIEmbeddingProvider,
                    difficulty_report=difficulty_reports.get(question.sha256),
                )
                findings = []
                if (
                    report.similarity.model is not None
                    and report.similarity.model != embedding.model
                ):
                    findings.append("EMBEDDING_MODEL_DRIFT")
                record = {
                    "case_id": case["case_id"],
                    "group": case["group"],
                    "expected": case["expected"],
                    "correct_option": case["question"]["correct_option"],
                    "protocol_findings": findings,
                    "report": report.model_dump(mode="json"),
                }
                stream.write(json.dumps(record, allow_nan=False) + "\n")
                stream.flush()
                records.append(record)
                write_summary(summary_stream, summary(records, len(cases)))
                print(
                    f"{len(records)}/{len(cases)} {case['case_id']}: {report.status}",
                    flush=True,
                )

        try:
            await asyncio.gather(*(run(case) for case in cases))
        finally:
            result = summary(records, len(cases))
            write_summary(summary_stream, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--difficulty-reports",
        type=Path,
        help="Existing concrete difficulty reports in JSONL; never assessed here",
    )
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    reports = (
        load_difficulty_reports(args.difficulty_reports)
        if args.difficulty_reports
        else None
    )
    result = asyncio.run(evaluate(args.output, difficulty_reports=reports))
    return (
        0
        if result["statuses"].get("assessed", 0) == result["requested"]
        and not result["protocol_failure_count"]
        and not result["mandatory_check_failure_count"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
