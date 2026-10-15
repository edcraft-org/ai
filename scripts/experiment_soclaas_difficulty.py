"""Preregistered low-call SocLaas rubric/schema ablations with fixed examples."""

import argparse
import asyncio
import hashlib
import json
import random
import subprocess
from collections import Counter
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Client

from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.difficulty_profiles import (
    PROFILE_VERSIONS,
    PROFILES,
    build_profile_request,
    worked_anchors,
)
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.mcp.server import create_validation_server
from scripts.evaluate_difficulty_dataset import (
    LEVELS,
    all_summaries,
    assessment,
    blinded_question,
    evaluate_item,
    load_dataset,
    summarize,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def profile_records(records, profile):
    return [r for r in records if r["profile"] == profile]


def macro_recall(records):
    matrix = summarize(records)["confusion_rows_reference_columns_judge"]
    rates = []
    for level in LEVELS:
        support = sum(r["reference"]["difficulty"] == level for r in records)
        if support:
            rates.append(matrix[level][level] / support)
    return sum(rates) / len(rates) if rates else None


def choose_candidate(records, prompt_lengths):
    """Only development records; failures count against per-class recall."""
    if not records or any(r["split"] != "development" for r in records):
        raise ValueError("candidate selection requires development records only")
    counts = {p: len(profile_records(records, p)) for p in PROFILES}
    if len(set(counts.values())) != 1 or not all(counts.values()):
        raise ValueError("profiles must have equal nonzero development coverage")

    def key(profile):
        subset = profile_records(records, profile)
        summary = summarize(subset)
        return (
            macro_recall(subset),
            summary["primary_agreement_all_items"]["count"],
            -sum(summary["failures"].values()),
            -prompt_lengths[profile],
            -PROFILES.index(profile),
        )

    return max(PROFILES, key=key)


def promotion_decision(records, candidate):
    """A frozen gate, not a second round of prompt/model tuning."""
    if candidate == "control":
        return "control"
    control = [
        r for r in records if r["profile"] == "control" and r["split"] == "held_out"
    ]
    selected = [
        r for r in records if r["profile"] == candidate and r["split"] == "held_out"
    ]
    if not control or len(control) != len(selected):
        raise ValueError("promotion requires matching held-out coverage")
    before, after = summarize(control), summarize(selected)
    return (
        candidate
        if macro_recall(selected) >= macro_recall(control)
        and after["primary_agreement_all_items"]["count"]
        >= before["primary_agreement_all_items"]["count"]
        and after["severe_disagreements"] <= before["severe_disagreements"]
        and sum(after["failures"].values()) <= sum(before["failures"].values())
        else "control"
    )


def experiment_summary(records):
    by_profile = [r | {"provider": r["profile"]} for r in records]
    summaries = all_summaries(by_profile)
    for profile, splits in summaries["providers"].items():
        for split, summary in splits.items():
            subset = [
                r
                for r in records
                if r["profile"] == profile and (split == "all" or r["split"] == split)
            ]
            summary["macro_recall"] = macro_recall(subset)
    return summaries


async def evaluate(args):
    data = load_dataset(args.dataset)
    if Counter(i["split"] for i in data["questions"]) != {
        "development": 18,
        "held_out": 12,
    }:
        raise ValueError("this bounded experiment requires the approved 18/12 split")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "dataset.json").write_bytes(args.dataset.read_bytes())
    rubric = load_code_difficulty_rubric()
    first = blinded_question(data["questions"][0])
    requests = {p: build_profile_request(first, rubric, profile=p) for p in PROFILES}
    prompt_lengths = {p: len(r.messages[0]["content"]) for p, r in requests.items()}
    provider = create_model_provider(TemplateProviderSelection(provider="soclaas"))
    settings = provider.generation_settings()
    if settings["response_format"] != "json_schema" or settings["max_retries"] != 0:
        raise ValueError("experiment requires strict schema and zero SDK retries")
    paths = sorted(
        [
            *ROOT.joinpath("src").rglob("*.py"),
            Path(__file__).resolve(),
            ROOT / "scripts/evaluate_difficulty_dataset.py",
        ]
    )
    seed = random.Random(43)
    schedule = []
    for item in data["questions"]:
        if item["split"] == "development":
            order = list(PROFILES)
            seed.shuffle(order)
            schedule.extend(
                {"question_id": item["question_id"], "profile": p} for p in order
            )
    manifest = {
        "protocol": "soclaas-difficulty-ablations-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_sha256": sha(
            b"".join(
                p.relative_to(ROOT).as_posix().encode() + b"\0" + p.read_bytes() + b"\0"
                for p in paths
            )
        ),
        "dataset_sha256": sha(args.dataset.read_bytes()),
        "rubric_sha256": rubric.sha256,
        "rubric_version": rubric.version,
        "provider": {
            "provider": "soclaas",
            "model": provider.model,
            "settings": settings,
        },
        "timeout_seconds": args.timeout_seconds,
        "profiles": {
            p: {
                "prompt_version": PROFILE_VERSIONS[p],
                "system_prompt_sha256": sha(r.messages[0]["content"].encode()),
                "system_prompt_characters": prompt_lengths[p],
                "response_schema_sha256": sha(
                    json.dumps(
                        r.response_model.model_json_schema(), sort_keys=True
                    ).encode()
                ),
            }
            for p, r in requests.items()
        },
        "examples": {
            "new_examples": 0,
            "core_worked_anchors": 3,
            "sha256": [sha(a.encode()) for a in worked_anchors(rubric)],
            "source": (
                "existing rubric training anchors only; "
                "no evaluation examples/labels inserted"
            ),
        },
        "development_schedule": schedule,
        "policy": {
            "max_calls": 96,
            "development": (
                "18 questions x four fixed profiles; "
                "interleaved deterministic order seed 43"
            ),
            "selection": (
                "Development only: highest macro recall including errors as "
                "nonmatches; ties by exact matches, fewer invalid reports, "
                "shorter system prompt, then profile order."
            ),
            "held_out": (
                "After saving selection, evaluate control and the selected profile "
                "on all 12 unchanged reserved items. If control selected, evaluate "
                "it once. Previously inspected set: regression evidence, "
                "not fresh confirmation."
            ),
            "promotion": (
                "Promote selected profile only if reserved macro recall and "
                "all-item agreement are no lower than control, severe disagreements "
                "and invalid reports no higher. Otherwise retain control. "
                "No alternative candidate chosen after reserved results."
            ),
            "checks": (
                "One application call per question/profile, no corrections or "
                "replacement judgments; SDK retries zero; concurrency three total."
            ),
            "blinding": (
                "Explicit MCQ field allowlist, requested difficulty null; "
                "reference labels/reasons/dimensions, IDs, solutions, split "
                "and topic never sent to the judge."
            ),
            "references": (
                "Original approved dataset bytes and split unchanged. "
                "Single-human AI-assisted labels; no new human "
                "or learner calibration claimed."
            ),
        },
    }
    write_json(args.output / "manifest.json", manifest)
    semaphore = asyncio.Semaphore(3)
    records = []
    items = {i["question_id"]: i for i in data["questions"]}
    async with AsyncExitStack() as stack:
        clients = {}
        for profile in PROFILES:
            folder = args.output / profile
            folder.mkdir()
            server = create_validation_server(
                difficulty_provider_factory=lambda: create_model_provider(
                    TemplateProviderSelection(provider="soclaas")
                ),
                difficulty_request_builder=partial(
                    build_profile_request, profile=profile
                ),
                difficulty_judge_timeout_seconds=args.timeout_seconds,
            )
            clients[profile] = await stack.enter_async_context(
                Client(server, timeout=args.timeout_seconds + 20)
            )

        async def run(job):
            async with semaphore:
                profile = job["profile"]
                record = await evaluate_item(
                    clients[profile],
                    "soclaas",
                    items[job["question_id"]],
                    args.output / profile,
                    args.timeout_seconds,
                )
                record["profile"] = profile
                write_json(
                    args.output / profile / f"soclaas-{job['question_id']}.json", record
                )
                value = assessment(record)
                print(
                    f"profile={profile} question={job['question_id']} "
                    f"estimate={value['estimated_difficulty'] if value else 'error'}",
                    flush=True,
                )
                return record

        records.extend(await asyncio.gather(*[run(job) for job in schedule]))
        candidate = choose_candidate(records, prompt_lengths)
        selection = {
            "generated_at": datetime.now(UTC).isoformat(),
            "candidate": candidate,
            "development": experiment_summary(records),
        }
        write_json(args.output / "selection.json", selection)
        print(f"DEVELOPMENT SELECTION: {candidate}", flush=True)
        held_profiles = (
            ["control"] if candidate == "control" else ["control", candidate]
        )
        held_schedule = []
        for item in data["questions"]:
            if item["split"] == "held_out":
                order = list(held_profiles)
                seed.shuffle(order)
                held_schedule.extend(
                    {"question_id": item["question_id"], "profile": p} for p in order
                )
        write_json(args.output / "held-out-schedule.json", held_schedule)
        records.extend(await asyncio.gather(*[run(job) for job in held_schedule]))
    results = {
        "manifest": manifest,
        "selection": selection,
        "records": records,
        "promoted_profile": promotion_decision(records, candidate),
    }
    write_json(args.output / "results.json", results)
    write_json(args.output / "summary.json", experiment_summary(records))
    print(f"PROMOTED PROFILE: {results['promoted_profile']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("reference_sets/python_tracing/dataset.json"),
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=250)
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file)
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
