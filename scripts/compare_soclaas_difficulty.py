"""Compare a SoCLaaS model with Qwen using its exact frozen v0.3 requests."""

import argparse
import asyncio
import csv
import json
import os
import random
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from edcraft_validator.llm.judging import run_judge
from scripts.evaluate_matrix_difficulty import make_summary
from scripts.evaluate_trace_difficulty import (
    DIMENSIONS,
    Assessment,
    build_request,
    digest,
)
from scripts.retry_trace_difficulty_transport import (
    RetryProvider,
    consistency_findings,
    is_transport,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "trace-difficulty-v0.3-model-comparison-r1"


def validate_frozen_requests(dataset, rubric, baseline):
    """Fail before inference if reference, rubric, schema or messages drift."""
    if digest(dataset) != baseline["dataset_sha256"]:
        raise ValueError("Dataset differs from the Qwen baseline")
    if digest(rubric) != baseline["rubric_sha256"]:
        raise ValueError("Rubric differs from the Qwen baseline")
    questions = json.loads(dataset)["questions"]
    requests = {}
    for q in questions:
        request = build_request(q, rubric.decode())
        frozen = baseline["requests"][q["question_id"]]
        actual = {
            "messages": request.messages,
            "schema": Assessment.model_json_schema(),
            "prompt_version": request.prompt_version,
            "schema_name": request.schema_name,
        }
        if actual != frozen:
            raise ValueError("Request differs from the Qwen baseline")
        requests[q["question_id"]] = request
    return questions, requests


def paired_comparison(records, baseline):
    previous = {(r["question_id"], r["repetition"]): r for r in baseline}
    pairs = Counter()
    changes = []
    for r in records:
        before = previous[(r["question_id"], r["repetition"])]
        if r["reference"] != before["reference"]:
            raise ValueError("Reference drift during comparison")
        if is_transport(r) or is_transport(before):
            continue
        old = before["prediction"] == before["reference"]["difficulty"]
        new = r["prediction"] == r["reference"]["difficulty"]
        pairs[(old, new)] += 1
        if old != new:
            changes.append(
                {
                    "question_id": r["question_id"],
                    "repetition": r["repetition"],
                    "reference": r["reference"]["difficulty"],
                    "qwen": before["prediction"],
                    "candidate": r["prediction"],
                    "candidate_improved": new,
                }
            )
    return {
        "paired_slots": sum(pairs.values()),
        "both_correct": pairs[(True, True)],
        "qwen_only_correct": pairs[(True, False)],
        "candidate_only_correct": pairs[(False, True)],
        "both_wrong": pairs[(False, False)],
        "changes": changes,
    }


def bootstrap(records):
    clusters = {}
    for r in records:
        if not is_transport(r):
            clusters.setdefault(r["code_family"], []).append(r)
    if not clusters:
        return None
    keys = list(clusters)
    rng = random.Random(86)
    values = []
    for _ in range(2000):
        sample = [r for _ in keys for r in clusters[rng.choice(keys)]]
        values.append(
            sum(r["prediction"] == r["reference"]["difficulty"] for r in sample)
            / len(sample)
        )
    values.sort()
    return {
        "interval_95": [values[49], values[1949]],
        "replicates": 2000,
        "seed": 86,
        "exact_code_family_clusters": len(keys),
        "scope": "Descriptive; repetitions retained together, not unseen accuracy.",
    }


def resume_state(path, model, frozen_requests):
    if path is None:
        return {}, [], []
    parent = json.loads((path / "manifest.json").read_text())
    if parent["model"] != model or parent["requests"] != frozen_requests:
        raise ValueError("Recovery model or frozen requests differ")
    attempts = [
        json.loads(line) for line in (path / "attempts.jsonl").read_text().splitlines()
    ]
    slots = {(r["question_id"], r["repetition"]): r for r in attempts}
    audit = json.loads((path / "operator-recovery.json").read_text())
    return slots, attempts, audit["inferred_interrupted_requests"]


def attempt_plan(
    question_id, repetition, slots, attempts, interrupted, extra_transport_retries=0
):
    key = (question_id, repetition)
    if key in slots and not is_transport(slots[key]):
        return []  # Includes completed misclassifications and content errors.
    history = [r for r in attempts if (r["question_id"], r["repetition"]) == key]
    failures = sum(is_transport(r) for r in history)
    interrupted_numbers = [
        r["attempt"] for r in interrupted if (r["question_id"], r["repetition"]) == key
    ]
    start = max([r["attempt"] for r in history] + interrupted_numbers + [0]) + 1
    return list(range(start, start + max(0, 2 + extra_transport_retries - failures)))


async def evaluate(args):
    dataset_path = ROOT / "reference_sets/python_tracing/dataset.json"
    rubric_path = ROOT / "docs/difficulty-rubric-v0.3.md"
    dataset, rubric = dataset_path.read_bytes(), rubric_path.read_bytes()
    parent = json.loads((args.baseline / "manifest.json").read_text())
    questions, requests = validate_frozen_requests(dataset, rubric, parent)
    previous = [
        json.loads(line) for line in args.baseline_records.read_text().splitlines()
    ]
    if len(previous) != 60 or parent["repetitions"] != 2:
        raise ValueError("Expected the complete two-pass Qwen baseline")
    catalogue = json.loads(args.catalogue.read_text())
    model_info = next(m for m in catalogue["data"] if m["id"] == args.model)
    display = model_info.get("soclaas", {}).get("display_name")
    if display != args.expected_display_name:
        raise ValueError("Candidate model catalogue identity does not match")
    slots, attempts, interrupted = resume_state(
        args.resume, args.model, parent["requests"]
    )
    inherited_attempts = len(attempts)
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["SOCLAAS_RESPONSE_FORMAT"] = parent["settings"]["response_format"]
    os.environ["SOCLAAS_GENERATION_MAX_TOKENS"] = str(
        parent["settings"]["generation_max_tokens"]
    )
    effort = parent["settings"].get("reasoning_effort", "provider_default")
    os.environ["SOCLAAS_REASONING_EFFORT"] = (
        "default" if effort == "provider_default" else effort
    )

    def provider():
        return RetryProvider(
            model=args.model,
            client=OpenAI(
                api_key=os.environ["SOCLAAS_API_KEY"],
                base_url=os.environ["SOCLAAS_BASE_URL"],
                timeout=None,
                max_retries=0,
            ),
        )

    initial = provider()
    settings = initial.generation_settings()
    initial.client.close()
    sources = sorted((ROOT / "src").rglob("*.py")) + sorted(
        (ROOT / "scripts").glob("*.py")
    )
    manifest = {
        "protocol": PROTOCOL if args.resume is None else PROTOCOL + "-recovery-r2",
        "created_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {
            str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sources
        },
        "baseline_manifest_sha256": digest(
            (args.baseline / "manifest.json").read_bytes()
        ),
        "baseline_records_sha256": digest(args.baseline_records.read_bytes()),
        "dataset_sha256": digest(dataset),
        "rubric_sha256": digest(rubric),
        "model": args.model,
        "model_display_name": display,
        "settings": settings,
        "model_catalogue": catalogue,
        "catalogue_file_mtime": args.catalogue.stat().st_mtime,
        "judge_timeout_seconds": None,
        "repetitions": 2,
        "concurrency": args.concurrency,
        "transport_retries_per_slot": 1 + args.extra_transport_retries,
        "availability_backoff_seconds": [5, 10, 20, 40, 60],
        "retry_policy": (
            "Retry a transport failure immediately after releasing its "
            "concurrency slot. Never retry content errors, abstentions "
            "or misclassifications."
        ),
        "primary_metric": (
            "Raw model overall-label matches / recorded assessment "
            "slots excluding transport failures. Content failures and "
            "abstentions are nonmatches; coverage and attempts are "
            "separate."
        ),
        "reference_scope": (
            "All 30 inspected during rubric development; descriptive "
            "reference agreement, not independent held-out or learner "
            "accuracy."
        ),
        "comparison_limitations": [
            "Same frozen v0.3 prompts, schema, labels, input and "
            "generation budget; only model and transport deadline "
            "protocol differ.",
            "Historical Qwen initial calls used finite deadlines; its "
            "three transport retries and this candidate run use no "
            "client/judge deadline.",
            "Serving aliases and provider-default sampling do not pin "
            "weights or deterministic sampling.",
            "Existing production MCP v0.2 is unchanged; v0.3 is the "
            "active reference/evaluation version.",
        ],
        "cases": questions,
        "requests": parent["requests"],
    }
    if args.resume is not None:
        manifest["recovery"] = {
            "parent_directory": str(args.resume.resolve()),
            "parent_manifest_sha256": digest(
                (args.resume / "manifest.json").read_bytes()
            ),
            "parent_attempts_sha256": digest(
                (args.resume / "attempts.jsonl").read_bytes()
            ),
            "operator_audit": json.loads(
                (args.resume / "operator-recovery.json").read_text()
            ),
            "retained_completed_attempts": inherited_attempts,
            "policy": (
                "No completed non-transport assessment is rerun or changed. "
                "Interrupted requests remain separate from transport and "
                "accuracy failures."
            ),
        }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output / "dataset-snapshot.json").write_bytes(dataset)
    (args.output / "rubric-snapshot.md").write_bytes(rubric)
    (args.output / "baseline-records.jsonl").write_bytes(
        args.baseline_records.read_bytes()
    )
    for p in sources:
        dest = args.output / "source-snapshot" / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
    semaphore = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    unavailable_count = 0
    backoff_until = 0.0

    def save():
        records = list(slots.values())
        result = make_summary(
            records, attempts, questions, 2, time.perf_counter() - started
        )
        result["inherited_attempts"] = inherited_attempts
        result["operator_interrupted_attempts"] = len(interrupted)
        result["planned_classification_coverage"] = result["scored"] / 60
        result["paired_with_qwen"] = paired_comparison(records, previous)
        result["qwen_baseline"] = {"correct": 47, "scored": 60, "accuracy": 47 / 60}
        pricing = model_info.get("soclaas", {})
        if all(
            k + "_microdollars_per_million_tokens" in pricing
            for k in ["input", "output"]
        ):
            result["reported_token_metering_equivalent_usd"] = sum(
                result["reported_" + k + "_tokens"]
                * pricing[k + "_microdollars_per_million_tokens"]
                / 1e12
                for k in ["input", "output"]
            )
        result["cost_note"] = (
            "Catalogue metering equivalent, not personal billing; "
            "unreported failed-attempt usage is not included."
        )
        (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        (args.output / "records.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in records)
        )
        return result

    with (
        (args.output / "attempts.jsonl").open("x") as stream,
        (args.output / "starts.jsonl").open("x") as starts,
    ):
        for prior_attempt in attempts:
            stream.write(json.dumps(prior_attempt) + "\n")
        stream.flush()
        save()

        async def run(q, rep):
            nonlocal unavailable_count, backoff_until
            for attempt in attempt_plan(
                q["question_id"],
                rep,
                slots,
                attempts,
                interrupted,
                args.extra_transport_retries,
            ):
                async with semaphore:
                    while time.perf_counter() < backoff_until:
                        await asyncio.sleep(
                            min(60, backoff_until - time.perf_counter())
                        )
                    starts.write(
                        json.dumps(
                            {
                                "question_id": q["question_id"],
                                "repetition": rep,
                                "attempt": attempt,
                                "started_at": datetime.now(UTC).isoformat(),
                            }
                        )
                        + "\n"
                    )
                    starts.flush()
                    client = provider()
                    try:
                        report = await run_judge(
                            requests[q["question_id"]],
                            provider_factory=lambda current=client: current,
                            timeout_seconds=None,
                        )
                    finally:
                        client.client.close()
                    a = (
                        report.assessment.model_dump(mode="json")
                        if report.assessment
                        else None
                    )
                    r = {
                        "question_id": q["question_id"],
                        "repetition": rep,
                        "attempt": attempt,
                        "topic": q["topic"],
                        "split": q["split"],
                        "code_family": digest(q["code"].encode()),
                        "reference": {
                            k: q[k]
                            for k in ["difficulty", "dimensions", "trace_event_count"]
                        },
                        "prediction": a["estimated_difficulty"] if a else None,
                        "dimension_predictions": {
                            k: a["dimensions"][k]["rating"] for k in DIMENSIONS
                        }
                        if a
                        else {},
                        "predicted_event_count": a["trace_event_count"] if a else None,
                        "consistency_findings": consistency_findings(a),
                        "returned_model": (client.raw_response or {}).get("model"),
                        "raw_response": client.raw_response,
                        "diagnostic": client.diagnostic,
                        "report": report.model_dump(mode="json"),
                    }
                    http_status = (client.diagnostic or {}).get("http_status")
                    if http_status in {429, 502, 503, 504}:
                        unavailable_count += 1
                        pause = min(60, 5 * 2 ** min(unavailable_count - 1, 4))
                        backoff_until = max(backoff_until, time.perf_counter() + pause)
                        print(
                            f"Provider HTTP {http_status}; backoff {pause}s", flush=True
                        )
                    elif report.status == "completed":
                        unavailable_count = 0
                        backoff_until = 0.0
                    slots[(q["question_id"], rep)] = r
                    attempts.append(r)
                    stream.write(json.dumps(r) + "\n")
                    stream.flush()
                    result = save()
                    print(
                        f"{len(slots)}/60 {q['question_id']} r{rep} a{attempt}: "
                        f"{report.status} {r['prediction']}; "
                        f"{result['correct']}/{result['scored']} scored",
                        flush=True,
                    )
                if not is_transport(r):
                    break

        await asyncio.gather(*(run(q, rep) for rep in [1, 2] for q in questions))
    result = save()
    result["descriptive_cluster_bootstrap"] = bootstrap(list(slots.values()))
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    fields = [
        "question_id",
        "repetition",
        "reference",
        "prediction",
        "correct",
        "transport_excluded",
        "reference_events",
        "predicted_events",
    ]
    for k in DIMENSIONS:
        fields.extend(["reference_" + k, "predicted_" + k])
    with (args.output / "predictions.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in sorted(
            slots.values(), key=lambda r: (r["repetition"], r["question_id"])
        ):
            row = {k: r[k] for k in ["question_id", "repetition", "prediction"]}
            row.update(
                reference=r["reference"]["difficulty"],
                correct=None
                if is_transport(r)
                else r["prediction"] == r["reference"]["difficulty"],
                transport_excluded=is_transport(r),
                reference_events=r["reference"]["trace_event_count"],
                predicted_events=r["predicted_event_count"],
            )
            for k in DIMENSIONS:
                row["reference_" + k] = r["reference"]["dimensions"][k]
                row["predicted_" + k] = r["dimension_predictions"].get(k)
            writer.writerow(row)
    (args.output / "evidence-checksums.json").write_text(
        json.dumps(
            {
                str(p.relative_to(args.output)): digest(p.read_bytes())
                for p in args.output.rglob("*")
                if p.is_file()
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "correct",
                    "scored",
                    "accuracy",
                    "transport_excluded",
                    "attempts",
                ]
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-records", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--expected-display-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--extra-transport-retries", type=int, default=0)
    args = parser.parse_args()
    if args.extra_transport_retries < 0:
        parser.error("Extra transport retries cannot be negative")
    if not 1 <= args.concurrency <= 4:
        parser.error("Concurrency must be 1–4")
    load_dotenv(args.env_file, override=False)
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
