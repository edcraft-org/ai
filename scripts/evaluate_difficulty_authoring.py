"""Small opt-in cross-provider generation → difficulty → correction experiment."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Client

from edcraft_validator.application.difficulty_authoring import (
    author_question_with_difficulty,
)
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.llm.usage import ModelCallRecord, summarize_usage
from edcraft_validator.mcp.server import create_validation_server

CASES = (
    (
        "direct_arithmetic",
        "easy",
        "Create a Python tracing MCQ with a short sequence of arithmetic "
        "assignments and one concrete input. Ask for the return value. Choose "
        "distractors linked to plausible order-of-operations or assignment mistakes.",
    ),
    (
        "conditional_state",
        "medium",
        "Create a Python tracing MCQ involving a loop, conditional updates and an "
        "accumulator. Use a short concrete integer list and ask for the return value. "
        "Choose distractors linked to specific plausible tracing mistakes.",
    ),
    (
        "interacting_state",
        "hard",
        "Create a Python tracing MCQ with list processing and a helper function. "
        "Use several interacting state dependencies that matter to the returned "
        "value, while keeping the concrete input small enough for manual tracing. "
        "Choose distractors linked to specific plausible tracing mistakes.",
    ),
)


def summarize_records(records):
    results = {}
    for provider in sorted({record["provider"] for record in records}):
        subset = [r for r in records if r["provider"] == provider]
        corrections = [r for r in subset if len(r["attempts"]) > 1]
        correction_stages = [a for r in corrections for a in r["attempts"][1:]]

        def tool(attempt):
            return attempt.get("tool_output") or {}

        def primary_match(record, attempt):
            output = tool(attempt)
            value = (output.get("judge") or {}).get("assessment") or {}
            return (
                output.get("status") == "assessed"
                and value.get("estimated_difficulty") == record["requested_difficulty"]
            )

        calls = []
        changed_questions = 0
        for record in subset:
            previous_question = None
            for attempt in record["attempts"]:
                current_question = attempt.get("question")
                if current_question:
                    changed_questions += (
                        previous_question is not None
                        and current_question != previous_question
                    )
                    previous_question = current_question
                calls.extend(attempt["generation"]["model_calls"])
                output = tool(attempt)
                runs = output.get("judge_attempts") or (
                    [output["judge"]] if output.get("judge") else []
                )
                for run in runs:
                    calls.extend(run.get("model_calls", []))
        results[provider] = {
            "jobs": len(subset),
            "initial_primary_matches": sum(
                primary_match(r, r["attempts"][0]) for r in subset
            ),
            "initial_confirmed_matches": sum(
                tool(r["attempts"][0]).get("difficulty_match") == "matches"
                for r in subset
            ),
            "jobs_with_corrections": len(corrections),
            "correction_attempts": len(correction_stages),
            "changed_questions": changed_questions,
            "corrections_resolved_to_confirmed_match": sum(
                r["status"] == "matches" for r in corrections
            ),
            "final_primary_matches": sum(
                primary_match(r, r["attempts"][-1]) for r in subset
            ),
            "final_confirmed_matches": sum(r["status"] == "matches" for r in subset),
            "final_unable_to_assess": sum(
                r["status"] == "unable_to_assess" for r in subset
            ),
            "final_mismatch": sum(r["status"] == "mismatch" for r in subset),
            "final_errors": sum(r["status"] == "error" for r in subset),
            "usage": summarize_usage(
                [ModelCallRecord.model_validate(c) for c in calls]
            ).model_dump(),
        }
    return results


def source_fingerprint():
    paths = sorted(
        [
            *Path("src").rglob("*.py"),
            Path("scripts/evaluate_difficulty_authoring.py"),
            Path("docs/difficulty-rubric.md"),
        ]
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


async def evaluate_provider(provider, args):
    selection = TemplateProviderSelection(provider=provider)

    def factory():
        return create_model_provider(selection)

    server = create_validation_server(
        difficulty_provider_factory=factory,
        difficulty_judge_timeout_seconds=args.timeout_seconds,
    )
    records = []
    async with Client(server, timeout=4 * args.timeout_seconds + 20) as client:
        for case_id, requested, brief in CASES:
            print(f"{provider}/{case_id}: generating and assessing", flush=True)
            result = await author_question_with_difficulty(
                brief,
                requested,
                provider_factory=factory,
                tool_client=client,
                author_timeout_seconds=args.timeout_seconds,
                tool_timeout_seconds=4 * args.timeout_seconds + 10,
            )
            record = result.model_dump(mode="json") | {
                "case_id": case_id,
                "provider": provider,
                "source_fingerprint_sha256": args.source_fingerprint,
                "author_and_judge": "same configured provider/model; separate calls",
                "correctness": "not assessed by this difficulty-only experiment",
            }
            path = args.output / f"{provider}-{case_id}.json"
            path.write_text(json.dumps(record, indent=2) + "\n")
            records.append(record)
            decisions = [
                a.tool_output.difficulty_match
                if a.tool_output
                else a.generation.error_code
                for a in result.attempts
            ]
            print(f"{provider}/{case_id}: {result.status}; {decisions}", flush=True)
    return records


async def evaluate(args):
    args.output.mkdir(parents=True, exist_ok=False)
    args.source_fingerprint = source_fingerprint()
    providers = args.providers or (
        ("openai", "soclaas", "ollama") if args.provider == "all" else (args.provider,)
    )
    configurations = []
    for name in providers:
        provider = create_model_provider(TemplateProviderSelection(provider=name))
        configurations.append(
            {
                "provider": name,
                "model": provider.model,
                "settings": provider.generation_settings(),
            }
        )
    preregistration = {
        "experiment_version": "single-label-difficulty-correction-v3",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_fingerprint_sha256": args.source_fingerprint,
        "timeout_seconds": args.timeout_seconds,
        "providers": configurations,
        "cases": [
            {"id": key, "requested_difficulty": level, "brief": brief}
            for key, level, brief in CASES
        ],
        "policy": (
            "One initial generation plus up to three generation/question "
            "corrections. Each assessment permits up to three diagnostic error "
            "repairs; valid labels are not retried. No reference questions."
        ),
    }
    (args.output / "manifest.json").write_text(
        json.dumps(preregistration, indent=2) + "\n"
    )
    results = await asyncio.gather(*[evaluate_provider(p, args) for p in providers])
    manifest = {
        "experiment_version": "single-label-difficulty-correction-v3",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_fingerprint_sha256": args.source_fingerprint,
        "timeout_seconds": args.timeout_seconds,
        "cases": [
            {"id": key, "requested_difficulty": level, "brief": brief}
            for key, level, brief in CASES
        ],
        "providers": list(providers),
        "records": [record for records in results for record in records],
        "limitations": [
            "Small integration experiment; no provider ranking or calibration.",
            "Author and judge use the same provider/model in separate calls.",
            "No reference-set or held-out questions are used.",
            "Up to three corrections for generation errors, too_easy, too_hard "
            "or missing information; assessment errors get bounded repairs.",
            "No correctness checks or generated-code execution are performed.",
        ],
    }
    (args.output / "experiment.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output / "summary.json").write_text(
        json.dumps(summarize_records(manifest["records"]), indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--provider", choices=("all", "openai", "soclaas", "ollama"), default="all"
    )
    selection.add_argument(
        "--providers", nargs="+", choices=("openai", "soclaas", "ollama")
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file)
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
