"""Retry transport failures, preserving history and separate accuracy metrics."""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from edcraft_validator.llm.judging import run_judge
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from scripts.evaluate_trace_difficulty import (
    DIMENSIONS,
    Assessment,
    RecordingProvider,
    derived_level,
    metrics,
)

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT_ERRORS = {"JUDGE_TRANSPORT", "JUDGE_TIMEOUT"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_transport(record):
    return (
        record["report"]["status"] == "error"
        and record["report"]["error_code"] in TRANSPORT_ERRORS
    )


def classification_metrics(records):
    scored = [record for record in records if not is_transport(record)]
    result = metrics(scored, len(scored))
    result["accuracy"] = result.pop("accuracy_all_requested")
    result["scored"] = result.pop("requested")
    result["assessment_slots"] = len(records)
    result["transport_excluded"] = len(records) - len(scored)
    result["classification_coverage"] = len(scored) / len(records) if records else None
    return result


def safe_diagnostic(error):
    cause = error.__cause__ or error
    message = str(cause)
    for name, value in os.environ.items():
        if ("API_KEY" in name or "TOKEN" in name) and value:
            message = message.replace(value, "[REDACTED]")
    return {
        "exception_type": type(cause).__name__,
        "category": getattr(error, "category", None),
        "http_status": getattr(cause, "status_code", None),
        "request_id": getattr(cause, "request_id", None),
        "message": message[:2000],
    }


class RetryProvider(RecordingProvider):
    diagnostic = None

    def generate(self, request):
        try:
            return super().generate(request)
        except Exception as error:
            self.diagnostic = safe_diagnostic(error)
            raise


def consistency_findings(assessment):
    if not assessment:
        return []
    findings = []
    if derived_level(assessment["dimensions"]) != assessment["estimated_difficulty"]:
        findings.append("OVERALL_DIMENSION_RULE_INCONSISTENCY")
    count = assessment["trace_event_count"]
    if sum(assessment["event_breakdown"].values()) != count:
        findings.append("EVENT_BREAKDOWN_SUM_INCONSISTENCY")
    burden = (
        "unknown"
        if count is None
        else "low"
        if count <= 5
        else "moderate"
        if count <= 20
        else "high"
    )
    if assessment["dimensions"]["execution_burden"]["rating"] != burden:
        findings.append("EVENT_COUNT_BURDEN_INCONSISTENCY")
    return findings


async def evaluate(args):
    parent_path = args.parent / "manifest.json"
    parent = json.loads(parent_path.read_text())
    original_path = args.parent / "records.jsonl"
    original = [json.loads(line) for line in original_path.read_text().splitlines()]
    targets = [record for record in original if is_transport(record)]
    if len(targets) != 3:
        raise ValueError("Expected exactly the three original transport failures")
    if (
        sha256(ROOT / "reference_sets/python_tracing/dataset.json")
        != parent["dataset_sha256"]
    ):
        raise ValueError("Reference changed after the original run")
    if sha256(ROOT / "docs/difficulty-rubric-v0.3.md") != parent["rubric_sha256"]:
        raise ValueError("Rubric changed after the original run")
    for record in targets:
        frozen = parent["requests"][record["question_id"]]
        if frozen["schema"] != Assessment.model_json_schema():
            raise ValueError("Response schema drift")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["SOCLAAS_RESPONSE_FORMAT"] = parent["settings"]["response_format"]
    os.environ["SOCLAAS_GENERATION_MAX_TOKENS"] = str(
        parent["settings"]["generation_max_tokens"]
    )
    effort = parent["settings"].get("reasoning_effort", "provider_default")
    os.environ["SOCLAAS_REASONING_EFFORT"] = (
        "default" if effort == "provider_default" else effort
    )
    manifest = {
        "protocol": "trace-difficulty-transport-retry-v0.3-r2",
        "created_at": datetime.now(UTC).isoformat(),
        "parent_run": str(args.parent.resolve()),
        "parent_manifest_sha256": sha256(parent_path),
        "parent_records_sha256": sha256(original_path),
        "model": parent["model"],
        "dataset_sha256": parent["dataset_sha256"],
        "rubric_sha256": parent["rubric_sha256"],
        "client_timeout_seconds": None,
        "judge_timeout_seconds": None,
        "sdk_retries": 0,
        "application_retries_per_failed_slot": 1,
        "concurrency": 2,
        "unchanged": "Exact original messages, schema, model and generation "
        "settings; no label/prompt changes.",
        "accuracy_policy": "Exclude transport/time-out failed slots from "
        "classification denominators; other failures and "
        "abstentions remain nonmatches. Report transport coverage "
        "separately.",
        "merge_policy": "Replace only each targeted failed slot with its one new "
        "attempt, regardless of correctness; preserve all original "
        "attempts separately.",
        "targets": [
            {
                "question_id": r["question_id"],
                "repetition": r["repetition"],
                "request_sha256": r["report"]["request_sha256"],
            }
            for r in targets
        ],
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [
                Path(__file__),
                ROOT / "scripts/evaluate_trace_difficulty.py",
                ROOT / "src/edcraft_validator/llm/judging.py",
            ]
        },
        "server_timeout_note": "Disabling client/judge deadlines cannot disable an "
        "upstream service limit.",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    retries = []
    merged = {(r["question_id"], r["repetition"]): r for r in original}
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(2)

    def save_summary():
        records = list(merged.values())
        result = {
            "classification": classification_metrics(records),
            "before_retry_excluding_transport": classification_metrics(original),
            "by_repetition": {
                str(rep): classification_metrics(
                    [r for r in records if r["repetition"] == rep]
                )
                for rep in range(1, parent["repetitions"] + 1)
            },
            "retry_attempts_recorded": len(retries),
            "retry_attempts_planned": len(targets),
            "retry_classification": classification_metrics(retries),
            "all_attempts_including_history": len(original) + len(retries),
            "transport_failure_attempts_including_history": sum(
                is_transport(r) for r in original + retries
            ),
            "retry_wall_seconds": time.perf_counter() - started,
            "by_topic": {
                topic: classification_metrics(
                    [r for r in records if r["topic"] == topic]
                )
                for topic in sorted({r["topic"] for r in records})
            },
        }
        for key in ("input_tokens", "output_tokens"):
            values = [r["report"]["usage"][key] for r in original + retries]
            result["all_attempts_" + key] = (
                sum(values) if all(v is not None for v in values) else None
            )
            result["reported_" + key] = sum(v for v in values if v is not None)
        (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    with (args.output / "retry-records.jsonl").open("x") as stream:

        async def retry(record):
            async with semaphore:
                frozen = parent["requests"][record["question_id"]]
                request = StructuredGenerationRequest(
                    messages=frozen["messages"],
                    response_model=Assessment,
                    prompt_version=frozen["prompt_version"],
                    schema_name=frozen["schema_name"],
                )
                with OpenAI(
                    api_key=os.environ["SOCLAAS_API_KEY"],
                    base_url=os.environ["SOCLAAS_BASE_URL"],
                    timeout=None,
                    max_retries=0,
                ) as client:
                    provider = RetryProvider(client=client, model=parent["model"])
                    assert provider.client.timeout is None
                    report = await run_judge(
                        request, provider_factory=lambda: provider, timeout_seconds=None
                    )
                assert report.request_sha256 == record["report"]["request_sha256"]
                assessment = (
                    report.assessment.model_dump(mode="json")
                    if report.assessment
                    else None
                )
                result = {
                    **record,
                    "prediction": assessment["estimated_difficulty"]
                    if assessment
                    else None,
                    "dimension_predictions": {
                        key: assessment["dimensions"][key]["rating"]
                        for key in DIMENSIONS
                    }
                    if assessment
                    else {},
                    "predicted_event_count": assessment["trace_event_count"]
                    if assessment
                    else None,
                    "consistency_findings": consistency_findings(assessment),
                    "returned_model": (provider.raw_response or {}).get("model"),
                    "raw_response": provider.raw_response,
                    "report": report.model_dump(mode="json"),
                    "transport_diagnostic": provider.diagnostic,
                    "retry_of": {
                        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
                        "original_error": record["report"]["error_code"],
                    },
                }
                stream.write(json.dumps(result) + "\n")
                stream.flush()
                retries.append(result)
                merged[(record["question_id"], record["repetition"])] = result
                save_summary()
                print(
                    f"{len(retries)}/3 {record['question_id']}: {report.status}, "
                    f"prediction={result['prediction']}, "
                    f"reference={record['reference']['difficulty']}, "
                    f"error={report.error_code}",
                    flush=True,
                )
                if provider.diagnostic:
                    print(json.dumps(provider.diagnostic), flush=True)

        await asyncio.gather(*(retry(record) for record in targets))
    result = save_summary()
    records = sorted(merged.values(), key=lambda r: (r["repetition"], r["question_id"]))
    with (args.output / "merged-records.jsonl").open("x") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    fields = [
        "question_id",
        "repetition",
        "reference",
        "prediction",
        "transport_excluded",
        "correct",
        "retried",
    ]
    for key in DIMENSIONS:
        fields.extend(["reference_" + key, "predicted_" + key])
    with (args.output / "predictions.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {
                "question_id": record["question_id"],
                "repetition": record["repetition"],
                "reference": record["reference"]["difficulty"],
                "prediction": record["prediction"],
                "transport_excluded": is_transport(record),
                "correct": None
                if is_transport(record)
                else record["prediction"] == record["reference"]["difficulty"],
                "retried": "retry_of" in record,
            }
            for key in DIMENSIONS:
                row["reference_" + key] = record["reference"]["dimensions"][key]
                row["predicted_" + key] = record["dimension_predictions"].get(key)
            writer.writerow(row)
    print(json.dumps(result["classification"], indent=2), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    raise SystemExit(main())
