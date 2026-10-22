"""Review local relevance decisions without starting a generative judge call."""

import argparse
import asyncio
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

from edcraft_validator.application.code_relevance import (
    review_code_question_relevance,
)
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.relevance import (
    CodeQuestionRequest,
)
from edcraft_validator.llm.decision import (
    DEFAULT_RELEVANCE_THRESHOLD,
    QwenDecisionProvider,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "reference_sets/python_tracing/dataset.json"
CONTROLS = ROOT / "reference_sets/python_tracing/quality-controls.json"


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
                "request": CodeQuestionRequest(
                    prompt=f"Create a Python tracing MCQ about {raw['topic']}.",
                    answer_target=raw["answer_target"],
                    num_distractors=len(raw["options"]) - 1,
                    learner_prerequisites=["Understands the Python semantics shown."],
                ).model_dump(mode="json"),
                "expected": None,
            }
        )
    # Preserve the frozen control content. Only deterministic expectations are
    # scored; historical rubric expectations remain in the control source.
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
        CodeQuestionRequest.model_validate(case["request"])
    return cases


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
        scores = [
            r["report"]["relevance"]["decision"]["score"]
            for r in selected
            if r["report"]["relevance"]["decision"]["status"] == "assessed"
        ]
        groups[group] = {
            "recorded": len(selected),
            "technical": Counter(r["report"]["technical"]["status"] for r in selected),
            "requirements": Counter(
                r["report"]["requirements"]["status"] for r in selected
            ),
            "score_range": [min(scores), max(scores)] if scores else None,
            "control_disagreements": disagreements,
        }
    times = [r["report"]["duration_ms"] for r in records]
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
        "median_duration_ms": statistics.median(times) if times else None,
        "limitations": [
            "Decision scores and the chemistry pilot threshold are advisory; "
            "they do not establish Python relevance accuracy.",
            "Ambiguity and missing concepts can escape these checks.",
            "Difficulty judgments and their quality concerns are separate; "
            "this review never consumes another check's report.",
            "The held-out set has no human relevance labels; "
            "no relevance accuracy is claimed.",
            "Local model paths must contain the documented Qwen weights.",
        ],
    }


async def evaluate(output: Path) -> dict:
    cases = evaluation_cases(
        json.loads(DATASET.read_text()), json.loads(CONTROLS.read_text())
    )
    manifest_path = output.with_suffix(".manifest.json")
    summary_path = output.with_suffix(".summary.json")
    decision = QwenDecisionProvider()
    manifest = {
        "protocol": "code-relevance-evaluation-v5-decision",
        "relevance_tool_version": "2.0.0",
        "review_report_version": "5.0.0",
        "created_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "decision": {
            "provider": decision.provider,
            "model": decision.model,
            "threshold": DEFAULT_RELEVANCE_THRESHOLD,
        },
        "new_judge_calls": 0,
        "decision_deadline_seconds": 35,
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
                report = await review_code_question_relevance(
                    question,
                    CodeQuestionRequest.model_validate(case["request"]),
                    decision_provider_factory=lambda: decision,
                )
                findings = []
                if (
                    report.relevance.decision.model is not None
                    and report.relevance.decision.model != decision.model
                ):
                    findings.append("RELEVANCE_MODEL_DRIFT")
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
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    result = asyncio.run(evaluate(args.output))
    return (
        0
        if result["statuses"].get("assessed", 0) == result["requested"]
        and not result["protocol_failure_count"]
        and not result["mandatory_check_failure_count"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
