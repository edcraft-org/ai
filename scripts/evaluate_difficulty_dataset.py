"""Evaluate a frozen reference dataset through MCP without exposing its ratings."""

import argparse
import asyncio
import hashlib
import json
import random
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Client

from edcraft_validator.application.code_difficulty import CodeDifficultyReport
from edcraft_validator.domains.code.difficulty import (
    DIFFICULTY_PROMPT_VERSION,
    CodeDifficultyQuestion,
    build_difficulty_request,
    load_code_difficulty_rubric,
)
from edcraft_validator.domains.code.difficulty_matching import compare_difficulty
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.llm.usage import ModelCallRecord, summarize_usage
from edcraft_validator.mcp.server import create_validation_server

LEVELS = ("easy", "medium", "hard")
DIMENSIONS = (
    "execution_burden",
    "changing_state",
    "conceptual_interaction",
    "answer_discrimination",
)
ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "single-pass-difficulty-dataset-evaluation-v3"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def blinded_question(item):
    """Explicit allowlist; labels, reasons, solutions and metadata never enter MCP."""
    return CodeDifficultyQuestion.model_validate(
        {key: item[key] for key in CodeDifficultyQuestion.model_fields}
    )


def load_dataset(path):
    data = json.loads(path.read_bytes())
    if not data["questions"]:
        raise ValueError("dataset is empty")
    ids = [item["question_id"] for item in data["questions"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question IDs")
    for item in data["questions"]:
        blinded_question(item)
        if item["difficulty"] not in LEVELS:
            raise ValueError("unknown approved difficulty")
        if item["split"] not in {"development", "held_out"}:
            raise ValueError("unknown split")
        if set(item["dimensions"]) != set(DIMENSIONS) or any(
            rating not in {"low", "moderate", "high"}
            for rating in item["dimensions"].values()
        ):
            raise ValueError("invalid approved dimensions")
    if data["rubric_version"] != load_code_difficulty_rubric().version:
        raise ValueError("dataset and judge rubric versions differ")
    return data


def assessment(record):
    report = record.get("tool_output")
    if report and report["status"] in {"assessed", "unable_to_assess"}:
        return report["judge"]["assessment"]
    return None


def comparison_to_reference(value, requested):
    """Read old evidence without applying the new policy retroactively."""
    estimate = value["estimated_difficulty"]
    legacy = "alternative_levels" in value
    if estimate is None:
        return "uncertain" if legacy else "unable_to_assess"
    decision = compare_difficulty(estimate, requested)
    if legacy and any(
        compare_difficulty(a, requested) != decision
        for a in value["alternative_levels"]
    ):
        return "uncertain"
    return decision


def judge_attempts(record):
    """Read archived repair histories as well as current single-pass reports."""
    output = record.get("tool_output") or {}
    return output.get("judge_attempts") or (
        [output["judge"]] if output.get("judge") else []
    )


def first_pass_record(record):
    attempts = judge_attempts(record)
    if not attempts:
        return record
    first = attempts[0]
    value = first.get("assessment")
    status = (
        "error"
        if first["status"] != "completed"
        else (
            "unable_to_assess" if value["estimated_difficulty"] is None else "assessed"
        )
    )
    return record | {
        "tool_output": (record.get("tool_output") or {})
        | {
            "judge": first,
            "status": status,
            "error_code": first["error_code"],
        }
    }


def ratio(numerator, denominator):
    return {
        "count": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def ordinal_alpha(pairs):
    """Two-rater ordinal Krippendorff alpha, pooled midrank distances.

    Missing estimates supply no pair; coincidence marginals use paired items only.
    The expected-disagreement denominator samples without replacement.
    """
    if not pairs:
        return None
    counts = Counter(value for pair in pairs for value in pair)
    midranks = {}
    cumulative = 0
    for level in LEVELS:
        midranks[level] = cumulative + counts[level] / 2
        cumulative += counts[level]
    n = sum(counts.values())
    expected = sum(
        counts[a] * counts[b] * (midranks[a] - midranks[b]) ** 2
        for a in LEVELS
        for b in LEVELS
    ) / (n * (n - 1))
    if not expected:
        return None
    observed = sum((midranks[a] - midranks[b]) ** 2 for a, b in pairs) / len(pairs)
    return 1 - observed / expected


def summarize(records):
    confusion = {a: dict.fromkeys(LEVELS, 0) for a in LEVELS}
    dimensions = {name: [0, 0] for name in DIMENSIONS}
    pairs, errors, unknowns, uncertain, confirmed, decisive = [], Counter(), 0, 0, 0, 0
    for record in records:
        value = assessment(record)
        if value is None:
            report = record.get("tool_output") or {}
            errors[record.get("error_code") or report.get("error_code") or "ERROR"] += 1
            continue
        reference = record["reference"]
        estimate = value["estimated_difficulty"]
        if estimate is None:
            unknowns += 1
        else:
            pairs.append((reference["difficulty"], estimate))
            confusion[reference["difficulty"]][estimate] += 1
        decision = comparison_to_reference(value, reference["difficulty"])
        uncertain += decision == "uncertain"
        confirmed += decision == "matches"
        decisive += decision in {"matches", "too_easy", "too_hard"}
        for name in DIMENSIONS:
            rating = value["dimensions"][name]["rating"]
            if rating != "unknown":
                dimensions[name][1] += 1
                dimensions[name][0] += rating == reference["dimensions"][name]
    matches = sum(a == b for a, b in pairs)
    return {
        "total": len(records),
        "reference_support": dict(
            Counter(r["reference"]["difficulty"] for r in records)
        ),
        "assessed": len(records) - sum(errors.values()),
        "judge_labelled": len(pairs),
        "unknown_estimates": unknowns,
        "failures": dict(errors),
        "primary_agreement_all_items": ratio(matches, len(records)),
        "primary_agreement_jointly_labelled": ratio(matches, len(pairs)),
        "confirmed_reference_matches": ratio(confirmed, len(records)),
        "uncertain_comparisons": uncertain,
        "decision_coverage": ratio(decisive, len(records)),
        "confusion_rows_reference_columns_judge": confusion,
        "severe_disagreements": confusion["easy"]["hard"] + confusion["hard"]["easy"],
        "dimensions": {name: ratio(*counts) for name, counts in dimensions.items()},
        "ordinal_alpha": ordinal_alpha(pairs),
        "ordinal_alpha_paired_items": len(pairs),
        "ordinal_alpha_unavailable_reason": (
            "No paired labels or no pooled category variation"
            if ordinal_alpha(pairs) is None
            else None
        ),
    }


def bootstrap_intervals(records, *, replicates=2000, seed=43):
    """Resample whole supplied families; the final dataset has one item per family."""
    groups = defaultdict(list)
    for record in records:
        groups[record["family_id"]].append(record)
    if len(groups) < 2:
        return {"unavailable_reason": "Fewer than two families"}
    rng = random.Random(seed)
    families = list(groups)
    samples = defaultdict(list)
    for _ in range(replicates):
        draw = [
            r
            for family in rng.choices(families, k=len(families))
            for r in groups[family]
        ]
        summary = summarize(draw)
        for key in (
            "primary_agreement_all_items",
            "confirmed_reference_matches",
            "decision_coverage",
        ):
            samples[key].append(summary[key]["rate"])
        if summary["ordinal_alpha"] is not None:
            samples["ordinal_alpha"].append(summary["ordinal_alpha"])
    intervals = {}
    for key, values in samples.items():
        values.sort()
        intervals[key] = {
            "lower": values[int(0.025 * (len(values) - 1))],
            "upper": values[int(0.975 * (len(values) - 1))],
            "valid_replicates": len(values),
        }
    return {
        "method": "family percentile bootstrap, 95%",
        "replicates": replicates,
        "seed": seed,
        "families": len(families),
        "intervals": intervals,
    }


def all_summaries(records):
    result = {}
    for provider in sorted({r["provider"] for r in records}):
        result[provider] = {}
        for split in ("all", "development", "held_out"):
            subset = [
                r
                for r in records
                if r["provider"] == provider and (split == "all" or r["split"] == split)
            ]
            result[provider][split] = summarize(subset) | {
                "first_pass": summarize([first_pass_record(r) for r in subset]),
                "corrective_calls": sum(
                    max(len(judge_attempts(r)) - 1, 0) for r in subset
                ),
                "recovered_to_label": sum(
                    first_pass_record(r)["tool_output"]["status"] == "error"
                    and bool(assessment(r) and assessment(r)["estimated_difficulty"])
                    for r in subset
                    if r.get("tool_output")
                ),
                "bootstrap": bootstrap_intervals(subset),
                "topics": {
                    topic: summarize([r for r in subset if r["topic"] == topic])
                    for topic in sorted({r["topic"] for r in subset})
                },
            }
    calls = [
        ModelCallRecord.model_validate(call)
        for r in records
        for attempt in judge_attempts(r)
        for call in attempt.get("model_calls", [])
    ]
    return {"providers": result, "usage": summarize_usage(calls).model_dump()}


async def evaluate_item(client, provider, item, output, timeout):
    record = {
        "provider": provider,
        "question_id": item["question_id"],
        "family_id": item.get("family_id", item["question_id"]),
        "split": item["split"],
        "topic": item["topic"],
        "reference": {key: item[key] for key in ("difficulty", "dimensions")},
        "question": blinded_question(item).model_dump(mode="json"),
        "tool_output": None,
        "error_code": None,
    }
    try:
        response = await client.call_tool(
            "assess_code_difficulty",
            {"question": record["question"], "requested_difficulty": None},
            timeout=timeout + 10,
        )
        report = CodeDifficultyReport.model_validate(response.structured_content)
        if report.question_sha256 != blinded_question(item).sha256:
            raise ValueError("question hash changed")
        record["tool_output"] = report.model_dump(mode="json")
    except Exception as exc:
        # Record the failure category, never exception text with provider details.
        record["error_code"] = f"MCP_{type(exc).__name__}"
    write_json(output / f"{provider}-{item['question_id']}.json", record)
    value = assessment(record)
    result = (
        value["estimated_difficulty"]
        if value
        else (record["error_code"] or record["tool_output"]["error_code"])
    )
    print(f"{provider}/{item['question_id']}: {result}", flush=True)
    return record


async def evaluate_provider(provider, data, args):
    server = create_validation_server(
        difficulty_provider_factory=lambda: create_model_provider(
            TemplateProviderSelection(provider=provider)
        ),
        difficulty_judge_timeout_seconds=args.timeout_seconds,
    )
    semaphore = asyncio.Semaphore(1 if provider == "ollama" else 3)
    async with Client(server, timeout=args.timeout_seconds + 20) as client:

        async def run(item):
            async with semaphore:
                return await evaluate_item(
                    client, provider, item, args.output, args.timeout_seconds
                )

        # Keep split order explicit. No tuning between development and held-out calls.
        records = []
        for split in ("development", "held_out"):
            records.extend(
                await asyncio.gather(
                    *[run(item) for item in data["questions"] if item["split"] == split]
                )
            )
    return records


async def evaluate(args):
    data = load_dataset(args.dataset)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "dataset.json").write_bytes(args.dataset.read_bytes())
    rubric = load_code_difficulty_rubric()
    configurations = []
    for name in args.providers:
        provider = create_model_provider(TemplateProviderSelection(provider=name))
        configurations.append(
            {
                "provider": name,
                "model": provider.model,
                "settings": provider.generation_settings(),
            }
        )
    source_paths = sorted(
        [*ROOT.joinpath("src").rglob("*.py"), Path(__file__).resolve()]
    )
    manifest = {
        "protocol_version": PROTOCOL,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_id": data["dataset_id"],
        "dataset_sha256": sha256(args.dataset.read_bytes()),
        "dataset_revision": args.dataset_revision,
        "followup_of": args.followup_of,
        "judge_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": sha256(
            b"".join(
                p.relative_to(ROOT).as_posix().encode() + b"\0" + p.read_bytes() + b"\0"
                for p in source_paths
            )
        ),
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "prompt_version": DIFFICULTY_PROMPT_VERSION,
        "response_schema_sha256": sha256(
            json.dumps(
                build_difficulty_request(
                    blinded_question(data["questions"][0]), rubric
                ).response_model.model_json_schema(),
                sort_keys=True,
            ).encode()
        ),
        "providers": configurations,
        "judge_timeout_seconds": args.timeout_seconds,
        "policy": {
            "initial_assessments_per_item_per_provider": 1,
            "max_correction_attempts": 0,
            "repair_policy": "None. One assessment call; failures remain failures.",
            "question_corrections": 0,
            "remote_concurrency": 3,
            "local_concurrency": 1,
            "hidden_fields": [
                "difficulty",
                "dimensions",
                "difficulty_reason",
                "solution",
                "topic",
                "split",
                "provenance",
                "question_id",
            ],
            "scoring": (
                "Primary estimate exact agreement; errors and unknowns "
                "count as nonmatches over all items. Also retain "
                "single-label comparison against the reference. One pass only; "
                "historical repair metrics are zero for new runs."
            ),
            "family_grouping": (
                "Explicit family_id if present, otherwise question_id; "
                "final 30-item set contains distinct underlying code "
                "families."
            ),
            "original_authoring_target_metrics": (
                "Unavailable: final dataset omits original requested "
                "levels and reference match decisions. Do not fabricate "
                "false-acceptance/rejection or 4x4 decision confusion."
            ),
            "eligibility": (
                "All approved questions included; no additional "
                "correctness checks or execution."
            ),
            "human_agreement": (
                "AI-assisted single-human reference; independent "
                "human-human agreement unavailable."
            ),
            "held_out": (
                "Configuration frozen before all calls. Prior v2 seed "
                "questions and AI recommendations exist in branch "
                "history; this is not an untouched external benchmark. No "
                "within-run replacements or prompt tuning. A followup_of value "
                "identifies a requested repeat of an inspected collection, "
                "not fresh confirmatory validation."
            ),
            "alpha": (
                "Two-rater ordinal Krippendorff alpha with pooled "
                "marginal midrank distances, implementation in this "
                "runner v1; unknowns omitted from pairs."
            ),
            "intervals": (
                "2000 whole-family percentile bootstrap replicates; "
                "random.Random seed 43."
            ),
        },
    }
    write_json(args.output / "manifest.json", manifest)
    groups = await asyncio.gather(
        *[evaluate_provider(p, data, args) for p in args.providers]
    )
    records = [r for group in groups for r in group]
    write_json(args.output / "results.json", {"manifest": manifest, "records": records})
    write_json(args.output / "summary.json", all_summaries(records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument(
        "--followup-of", help="Prior evaluation identifier, if repeated"
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=("soclaas",),
        default=["soclaas"],
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
