"""Fixed real-provider authoring cases, usage summaries, and saved offline replay."""

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateRequest,
    ValidatedCodeTemplate,
)
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.llm.usage import ModelCallRecord, TokenUsage, summarize_usage

CASES_VERSION = "authoring-baseline-v1"
CASES = (
    (
        "addition",
        "easy",
        "Create a Python MCQ about adding two integers. "
        "Use two finite integer parameters and ask for the return value.",
    ),
    (
        "conditional",
        "easy",
        "Create a Python MCQ about an if/else choosing between two arithmetic "
        "results. Use finite integer parameters and ask for the return value.",
    ),
    (
        "accumulation",
        "medium",
        "Create a Python MCQ about accumulating a total in a for loop. "
        "Use finite integer parameters and ask for the return value.",
    ),
    (
        "list-sum",
        "medium",
        "Create a Python MCQ about summing an integer list using a for loop. "
        "Use a finite integer-list parameter and ask for the return value.",
    ),
    (
        "helper-in-loop",
        "hard",
        "Create a Python MCQ about a helper function called inside a loop. "
        "Use finite integer parameters and ask for the return value.",
    ),
)
PREVIEW_SEEDS = (0, 1, 42)


class ObservedProvider:
    """Optionally corrupt only the first answer for a separate correction drill."""

    def __init__(self, provider, inject_failure):
        self.delegate = provider
        self.provider = provider.provider
        self.model = provider.model
        self.inject_failure = inject_failure
        self.generation_calls = 0
        self.original_proposal = None

    @property
    def last_usage(self):
        return getattr(self.delegate, "last_usage", TokenUsage())

    def generation_settings(self):
        return self.delegate.generation_settings()

    def generate(self, request):
        self.generation_calls += 1
        response = self.delegate.generate(request)
        if self.inject_failure and self.generation_calls == 1:
            self.original_proposal = response.proposal.model_dump(mode="json")
            response = response.model_copy(
                update={
                    "proposal": response.proposal.model_copy(
                        update={
                            "answer_expression": (
                                f"({response.proposal.answer_expression}) + 1"
                            )
                        }
                    )
                }
            )
        return response

    def tool_turn(self, messages, tools):
        return self.delegate.tool_turn(messages, tools)


def summarize_records(records, requested_jobs):
    """Report denominators and all outcomes, including interrupted/unresolved jobs."""
    results = [
        record["authoring_result"] for record in records if "authoring_result" in record
    ]
    statuses = Counter(record["status"] for record in records)
    failed_first = [
        result
        for result in results
        if result["attempts"]
        and result["attempts"][0]["complete"]
        and not result["attempts"][0]["passed"]
    ]
    first_passes = sum(
        result["status"] == "checked" and len(result["attempts"]) == 1
        for result in results
    )
    corrected = sum(result["status"] == "checked" for result in failed_first)
    failures = Counter()
    check_findings = Counter()
    calls = []
    for record in records:
        result = record.get("authoring_result", {})
        if record["status"] != "checked":
            failure = result.get("failure") or record.get("failure")
            if failure:
                failures[f"{failure['stage']}:{failure['code']}"] += 1
            else:
                executions = (result.get("attempts") or [{}])[-1].get("executions", [])
                codes = {
                    finding["code"]
                    for execution in executions
                    for finding in (execution.get("evidence") or {}).get("findings", [])
                }
                if any(execution["error"] for execution in executions):
                    codes.add("TOOL_CALL_ERROR")
                for code in codes or {"unknown"}:
                    failures[code] += 1
        for attempt in result.get("attempts", []):
            for execution in attempt["executions"]:
                if execution["error"]:
                    check_findings["TOOL_CALL_ERROR"] += 1
                for finding in (execution["evidence"] or {}).get("findings", []):
                    check_findings[finding["code"]] += 1
        calls.extend(
            ModelCallRecord.model_validate(call)
            for call in result.get("model_calls", [])
        )
    durations = [record["duration_ms"] for record in records]
    usage = summarize_usage(calls).model_dump()
    return {
        "requested_jobs": requested_jobs,
        "recorded_jobs": len(records),
        "checked": statuses["checked"],
        "needs_review": statuses["needs_review"],
        "error": statuses["error"],
        "unresolved": requested_jobs - len(records),
        "checked_rate": statuses["checked"] / requested_jobs,
        "first_attempt_successes": first_passes,
        "first_attempt_success_rate": first_passes / requested_jobs,
        "correction_eligible_jobs": len(failed_first),
        "corrected_jobs": corrected,
        "correction_success_rate": corrected / len(failed_first)
        if failed_first
        else None,
        "attempts_per_job": [
            len(record.get("authoring_result", {}).get("attempts", []))
            for record in records
        ],
        "failure_counts": dict(failures),
        "check_finding_counts": dict(check_findings),
        "latency_ms": {
            "median": statistics.median(durations) if durations else None,
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
        },
        "usage": usage,
        "mean_model_calls_per_recorded_job": len(calls) / len(records)
        if records
        else None,
        "mean_input_tokens_per_recorded_job": usage["input_tokens"] / len(records)
        if records and usage["input_tokens"] is not None
        else None,
        "mean_output_tokens_per_recorded_job": usage["output_tokens"] / len(records)
        if records and usage["output_tokens"] is not None
        else None,
        "replay_passed_jobs": sum(
            record.get("replay_passed") is True for record in records
        ),
        "replay_failed_jobs": sum("replay_error" in record for record in records),
    }


def source_revision():
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    digest = hashlib.sha256()
    for path in sorted([*root.glob("src/**/*.py"), Path(__file__).resolve()]):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return {
        "git_revision": revision,
        "working_tree_dirty": dirty,
        "source_sha256": digest.hexdigest(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--jobs",
        type=int,
        help="total authoring jobs (default: five, or one for the drill)",
    )
    parser.add_argument("--correction-drill", action="store_true")
    args = parser.parse_args()
    jobs = args.jobs if args.jobs is not None else (1 if args.correction_drill else 5)
    if jobs < 1:
        parser.error("--jobs must be at least one")
    if args.env_file:
        load_dotenv(args.env_file)
    cases = CASES[:1] if args.correction_drill else CASES
    manifest = {
        **source_revision(),
        "cases_version": CASES_VERSION,
        "started_at": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "requested_model": args.model,
        "requested_jobs": jobs,
        "controlled_failure_injection": args.correction_drill,
        "preview_seeds": PREVIEW_SEEDS,
        "cases": [
            {"id": name, "difficulty": difficulty, "prompt": prompt}
            for name, difficulty, prompt in cases
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir = args.output.with_suffix("")
    artifact_dir.mkdir(exist_ok=True)
    write_json(args.output.with_suffix(".manifest.json"), manifest)
    summary_path = args.output.with_suffix(".summary.json")
    records = []
    write_json(summary_path, summarize_records(records, jobs))
    with args.output.open("w") as output:
        for index in range(jobs):
            case_id, difficulty, prompt = cases[index % len(cases)]
            job_id = f"{index + 1:03d}-{case_id}"
            request = CodeTemplateRequest(prompt=prompt, difficulty=difficulty)
            record = {
                "job_id": job_id,
                "case_id": case_id,
                "provider": args.provider,
                "request": request.model_dump(mode="json"),
                "status": "error",
            }
            started = time.perf_counter()
            provider = None
            result = None
            print(
                f"Starting {job_id}: {args.provider}/"
                f"{args.model or 'configured model'}",
                flush=True,
            )
            try:
                provider = ObservedProvider(
                    create_model_provider(
                        TemplateProviderSelection(
                            provider=args.provider, model=args.model
                        )
                    ),
                    args.correction_drill,
                )
                record["model"] = provider.model
                catalogue_path = artifact_dir / f"{job_id}.catalogue.json"

                def save_catalogue(snapshot, path=catalogue_path, job_record=record):
                    write_json(path, {"tools": snapshot.definitions()})
                    job_record["catalogue_file"] = path.name

                result = TemplateApplication().author_template(
                    request,
                    domain=CodeDomain(),
                    provider=provider,
                    on_catalogue_resolved=save_catalogue,
                )
                record["authoring_result"] = result.model_dump(mode="json")
                record["status"] = result.status
                if args.correction_drill:
                    record["original_model_proposal"] = provider.original_proposal
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["failure"] = {
                    "stage": "configuration" if provider is None else "unexpected",
                    "code": getattr(exc, "category", type(exc).__name__),
                }
            record["duration_ms"] = (time.perf_counter() - started) * 1000
            if result is not None and result.artifact is not None:
                try:
                    artifact_path = artifact_dir / f"{job_id}.template.json"
                    artifact_path.write_text(
                        result.artifact.model_dump_json(indent=2) + "\n"
                    )
                    loaded = ValidatedCodeTemplate.model_validate_json(
                        artifact_path.read_text()
                    )
                    app = TemplateApplication()
                    previews = []
                    for seed in PREVIEW_SEEDS:
                        original = app.generate_question(
                            result.artifact, domain=CodeDomain(), seed=seed
                        )
                        replay = app.generate_question(
                            loaded, domain=CodeDomain(), seed=seed
                        )
                        if original != replay:
                            raise ValueError(f"Offline replay differed for seed {seed}")
                        previews.append(replay.model_dump(mode="json"))
                    previews_path = artifact_dir / f"{job_id}.previews.json"
                    write_json(previews_path, previews)
                    record.update(
                        artifact_file=artifact_path.name,
                        preview_file=previews_path.name,
                        replay_passed=True,
                    )
                except Exception as exc:
                    record["replay_error"] = f"{type(exc).__name__}: {exc}"
            print(json.dumps(record), file=output, flush=True)
            records.append(record)
            summary = summarize_records(records, jobs)
            write_json(summary_path, summary)
            print(
                json.dumps(
                    {
                        "job_id": job_id,
                        "status": record["status"],
                        "attempts": len(
                            record.get("authoring_result", {}).get("attempts", [])
                        ),
                        "seconds": round(record["duration_ms"] / 1000, 3),
                        "reason": record.get("authoring_result", {}).get(
                            "reason", record.get("error")
                        ),
                    }
                ),
                flush=True,
            )
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["checked"] == jobs and not summary["replay_failed_jobs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
