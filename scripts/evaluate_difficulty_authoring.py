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
from edcraft_validator.mcp.server import create_validation_server

CASES = (
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
    async with Client(server, timeout=args.timeout_seconds + 10) as client:
        for case_id, requested, brief in CASES:
            print(f"{provider}/{case_id}: generating and assessing", flush=True)
            result = await author_question_with_difficulty(
                brief,
                requested,
                provider_factory=factory,
                tool_client=client,
                author_timeout_seconds=args.timeout_seconds,
                tool_timeout_seconds=args.timeout_seconds + 10,
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
    args.output.mkdir(parents=True, exist_ok=True)
    args.source_fingerprint = source_fingerprint()
    providers = (
        ("openai", "soclaas", "ollama") if args.provider == "all" else (args.provider,)
    )
    results = await asyncio.gather(*[evaluate_provider(p, args) for p in providers])
    manifest = {
        "experiment_version": "difficulty-correction-smoke-v1",
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
            "One correction on too_easy, too_hard or uncertain; errors stay errors.",
            "No correctness checks or generated-code execution are performed.",
        ],
    }
    (args.output / "experiment.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=("all", "openai", "soclaas", "ollama"), default="all"
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
