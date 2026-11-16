"""Fixed real-provider authoring cases, usage summaries, and saved offline replay."""

import argparse
import json
import statistics
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.domain_registry import create_domain
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.llm.usage import (
    ModelCallRecord,
    TokenUsage,
    close_provider,
    summarize_usage,
)

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
MATH_CASES_PATH = Path(__file__).with_name("math_authoring_cases.json")
PREVIEW_SEEDS = (0, 1, 42)
DOMAIN_CHOICES = ("code", "math")
SET_CHOICES = ("natural", "unsupported", "all")


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

    def close(self):
        close_provider(self.delegate)


def load_math_cases():
    """Read and validate the fixed mathematics prompt set once."""
    payload = json.loads(MATH_CASES_PATH.read_text())
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("math cases must be a non-empty list")

    seen = set()
    for case in cases:
        if set(case) != {"id", "set", "difficulty", "prompt"}:
            raise ValueError("each math case needs id, set, difficulty and prompt")
        if case["id"] in seen:
            raise ValueError(f"duplicate math case id {case['id']!r}")
        if case["set"] not in {"natural", "unsupported"}:
            raise ValueError(f"invalid math case set {case['set']!r}")
        if case["difficulty"] not in {"easy", "medium", "hard"}:
            raise ValueError(f"invalid math difficulty {case['difficulty']!r}")
        seen.add(case["id"])

    return payload["version"], tuple(cases)


MATH_CASES_VERSION, MATH_CASES = load_math_cases()


def _is_advisory(execution):
    """Advisory assessments never fail a template, so they are not failures."""
    details = (execution.get("evidence") or {}).get("details") or {}
    return execution.get("advisory") is True or details.get("advisory") is True


def _failure_codes(executions):
    """Derive root failure codes, folding blocked checks into their blocker."""
    codes = set()
    for execution in executions:
        if _is_advisory(execution):
            continue
        if execution.get("error"):
            codes.add("TOOL_CALL_ERROR")
        evidence = execution.get("evidence") or {}
        blocking = (evidence.get("details") or {}).get("blocking_code")
        for finding in evidence.get("findings", []):
            code = finding["code"]
            if code.endswith("_NOT_EVALUATED") and isinstance(blocking, str):
                # Mirror evaluation normalization: one structural cause, not
                # every check that was blocked by it.
                code = blocking
            codes.add(code)
    return codes


def _attempt_failure_codes(result):
    """Keep the failed check codes for every attempt, including corrected ones."""
    return [
        {
            "attempt": attempt.get("number", index),
            "codes": sorted(_failure_codes(attempt.get("executions", []))),
        }
        for index, attempt in enumerate(result.get("attempts", []), start=1)
    ]


def _last_execution_details(result, key):
    attempts = result.get("attempts") or []
    if not attempts:
        return None

    for execution in reversed(attempts[-1].get("executions", [])):
        details = (execution.get("evidence") or {}).get("details") or {}
        if key in details:
            return details
    return None


def _difficulty_record(result):
    details = _last_execution_details(result, "difficulty_outcome")
    if details is None:
        return None

    outcome = details["difficulty_outcome"]
    return {
        "requested": outcome.get("requested_difficulty")
        or (result.get("request") or {}).get("difficulty"),
        "estimated": outcome.get("estimated_difficulty"),
        "decision": outcome.get("decision"),
        "assessment_path": outcome.get("assessment_path"),
        "status": outcome.get("status"),
        "confidence": outcome.get("confidence"),
        "confidence_source": outcome.get("confidence_source"),
        "rubric_id": details.get("rubric_id"),
        "rubric_version": details.get("rubric_version"),
        "rubric_sha256": details.get("rubric_sha256"),
        "assessment_conditions_version": details.get("assessment_conditions_version"),
    }


def _relevance_record(result):
    details = _last_execution_details(result, "relevance_outcome")
    if details is None:
        return None

    outcome = details["relevance_outcome"]
    if outcome.get("relevant") is True:
        decision = "relevant"
    elif outcome.get("relevant") is False:
        decision = "not_relevant"
    else:
        decision = "unavailable"

    return {
        "score": outcome.get("score"),
        "threshold": outcome.get("threshold"),
        "relevant": outcome.get("relevant"),
        "decision": decision,
        "status": outcome.get("status"),
        "unavailable": outcome.get("unavailable"),
    }


def _coverage(result):
    validation = (result.get("artifact") or {}).get("validation") or {}
    if "examples_checked" in validation:
        return (
            validation.get("examples_checked"),
            validation.get("declared_domain_size"),
        )

    attempts = result.get("attempts") or []
    for attempt in reversed(attempts):
        for execution in reversed(attempt.get("executions", [])):
            details = (execution.get("evidence") or {}).get("details") or {}
            if "examples_checked" in details:
                return (
                    details.get("examples_checked"),
                    details.get("declared_domain_size"),
                )
    return None, None


def _token_pair(summary):
    if not isinstance(summary, dict):
        return {"input_tokens": None, "output_tokens": None, "model_call_count": 0}
    return {
        "input_tokens": summary.get("input_tokens"),
        "output_tokens": summary.get("output_tokens"),
        "model_call_count": summary.get("model_call_count", 0),
    }


def _sum_token_pairs(summaries):
    summaries = [summary for summary in summaries if isinstance(summary, dict)]
    if not summaries:
        return {"input_tokens": 0, "output_tokens": 0, "model_call_count": 0}

    def total(key):
        values = [summary.get(key) for summary in summaries]
        return None if any(value is None for value in values) else sum(values)

    return {
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "model_call_count": sum(
            summary.get("model_call_count") or 0 for summary in summaries
        ),
    }


def _author_tokens(result):
    if not result:
        return {"input_tokens": None, "output_tokens": None, "model_call_count": 0}
    return _token_pair(result.get("usage") or {})


def _judge_tokens(result):
    if not result:
        return {"input_tokens": 0, "output_tokens": 0, "model_call_count": 0}

    summaries = []
    for attempt in result.get("attempts", []):
        for execution in attempt.get("executions", []):
            details = (execution.get("evidence") or {}).get("details") or {}
            if details.get("advisory") is True and isinstance(
                details.get("usage"), dict
            ):
                summaries.append(details["usage"])
    return _sum_token_pairs(summaries)


def _outcome_for_status(status):
    if status == "checked":
        return "checked"
    if status == "needs_review":
        return "needs_review"
    return "failed"


def _record_author_tokens(record):
    if "author_tokens" in record:
        return record["author_tokens"]
    return _author_tokens(record.get("authoring_result"))


def _record_judge_tokens(record):
    if "judge_tokens" in record:
        return record["judge_tokens"]
    return _judge_tokens(record.get("authoring_result"))


def _record_case_set(record):
    return record.get("case_set", "natural")


def _record_outcome(record):
    return record.get("outcome") or _outcome_for_status(record.get("status", "error"))


def summarize_records(records, requested_jobs, requested_sets=None):
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
            if failure and failure.get("code") not in {
                "TEMPLATE_CHECKS_FAILED",
                "CHECK_ERROR",
            }:
                failures[f"{failure['stage']}:{failure['code']}"] += 1
            else:
                executions = (result.get("attempts") or [{}])[-1].get("executions", [])
                codes = _failure_codes(executions)
                for code in codes or {"unknown"}:
                    failures[code] += 1
        for attempt in result.get("attempts", []):
            for execution in attempt["executions"]:
                if _is_advisory(execution):
                    continue
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

    outcomes = {
        "checked": statuses["checked"],
        "needs_review": statuses["needs_review"],
        "failed": statuses["error"],
        "unresolved": requested_jobs - len(records),
    }

    by_set_outcomes = {}
    recorded_by_set = Counter()
    for record in records:
        set_name = _record_case_set(record)
        recorded_by_set[set_name] += 1
        bucket = by_set_outcomes.setdefault(
            set_name,
            {"checked": 0, "needs_review": 0, "failed": 0},
        )
        bucket[_record_outcome(record)] += 1

    requested_by_set = (
        Counter(requested_sets)
        if requested_sets is not None
        else Counter(recorded_by_set)
    )
    by_set = {}
    for set_name in sorted(set(requested_by_set) | set(by_set_outcomes)):
        requested = requested_by_set.get(set_name, 0)
        recorded = recorded_by_set.get(set_name, 0)
        bucket = {
            "requested_jobs": requested,
            "recorded_jobs": recorded,
            **by_set_outcomes.get(
                set_name, {"checked": 0, "needs_review": 0, "failed": 0}
            ),
        }
        bucket["unresolved"] = max(requested - recorded, 0)
        bucket["checked_rate"] = bucket["checked"] / requested if requested else None
        by_set[set_name] = bucket

    agreement = {}
    for record in records:
        difficulty = record.get("difficulty") or {}
        requested = difficulty.get("requested") or (record.get("request") or {}).get(
            "difficulty", "unknown"
        )
        estimated = difficulty.get("estimated") or "unavailable"
        agreement.setdefault(requested, Counter())[estimated] += 1
    difficulty_agreement = {
        requested: dict(sorted(estimates.items()))
        for requested, estimates in sorted(agreement.items())
    }
    difficulty_decisions = Counter(
        (record.get("difficulty") or {}).get("decision") or "unavailable"
        for record in records
    )

    unsupported = [
        record for record in records if _record_case_set(record) == "unsupported"
    ]
    unsupported_relevance = Counter()
    unsupported_relevance_jobs = []
    for record in unsupported:
        relevance = record.get("relevance") or {}
        decision = relevance.get("decision") or "unavailable"
        unsupported_relevance[decision] += 1
        unsupported_relevance_jobs.append(
            {
                "job_id": record.get("job_id"),
                "case_id": record.get("case_id"),
                "decision": decision,
                "score": relevance.get("score"),
                "threshold": relevance.get("threshold"),
            }
        )

    revision_histogram = Counter()
    for result in results:
        revisions = max(len(result.get("attempts", [])) - 1, 0)
        revision_histogram[str(revisions)] += 1

    author_tokens = _sum_token_pairs(
        [_record_author_tokens(record) for record in records]
    )
    judge_tokens = _sum_token_pairs(
        [_record_judge_tokens(record) for record in records]
    )
    combined_tokens = _sum_token_pairs([author_tokens, judge_tokens])

    return {
        "requested_jobs": requested_jobs,
        "recorded_jobs": len(records),
        "checked": statuses["checked"],
        "needs_review": statuses["needs_review"],
        "error": statuses["error"],
        "unresolved": requested_jobs - len(records),
        "outcomes": outcomes,
        "by_set": by_set,
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
        "revisions": {
            "histogram": dict(sorted(revision_histogram.items())),
            "total": sum(
                max(len(result.get("attempts", [])) - 1, 0) for result in results
            ),
        },
        "failure_counts": dict(failures),
        "failure_taxonomy": dict(sorted(check_findings.items())),
        "check_finding_counts": dict(check_findings),
        "difficulty_agreement": difficulty_agreement,
        "difficulty_decisions": dict(sorted(difficulty_decisions.items())),
        "relevance_flags_on_unsupported": {
            "counts": dict(sorted(unsupported_relevance.items())),
            "jobs": unsupported_relevance_jobs,
        },
        "latency_ms": {
            "median": statistics.median(durations) if durations else None,
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
        },
        "median_latency_ms": statistics.median(durations) if durations else None,
        "max_latency_ms": max(durations) if durations else None,
        "usage": usage,
        "token_totals": {
            "author": author_tokens,
            "judge": judge_tokens,
            "combined": combined_tokens,
        },
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

    return {
        "git_revision": revision,
        "working_tree_dirty": dirty,
    }


def _code_cases():
    return tuple(
        {
            "id": name,
            "set": "natural",
            "difficulty": difficulty,
            "prompt": prompt,
        }
        for name, difficulty, prompt in CASES
    )


def _cases_for(domain_name, set_name):
    if domain_name == "code":
        version, cases = CASES_VERSION, _code_cases()
    else:
        version, cases = MATH_CASES_VERSION, MATH_CASES

    if set_name != "all":
        cases = tuple(case for case in cases if case["set"] == set_name)
    return version, cases


def _domain_versions(domain_name):
    if domain_name != "math":
        return {"prompt_versions": [], "rubric_versions": []}

    from edcraft_validator.domains.math.difficulty import (
        load_math_difficulty_rubric,
    )
    from edcraft_validator.domains.math.prompt_builder import (
        MATH_TEMPLATE_PROMPT_VERSION,
    )

    rubric = load_math_difficulty_rubric()
    return {
        "prompt_versions": [f"{MATH_TEMPLATE_PROMPT_VERSION}+response-v1"],
        "rubric_versions": [
            {
                "rubric_id": rubric.rubric_id,
                "version": rubric.version,
                "sha256": rubric.sha256,
                "assessment_conditions_version": (rubric.assessment_conditions_version),
                "reasoning_prompt_version": rubric.reasoning_prompt_version,
                "decision_prompt_version": rubric.decision_prompt_version,
            }
        ],
    }


def _update_manifest(manifest, records):
    manifest["resolved_model"] = next(
        (record["model"] for record in reversed(records) if record.get("model")),
        None,
    )
    manifest["provider_settings"] = next(
        (
            record["provider_settings"]
            for record in reversed(records)
            if record.get("provider_settings")
        ),
        None,
    )

    prompt_versions = set(manifest.get("prompt_versions", []))
    rubric_versions = {
        (item.get("rubric_id"), item.get("version")): item
        for item in manifest.get("rubric_versions", [])
    }
    for record in records:
        prompt_version = (record.get("authoring_result") or {}).get("prompt_version")
        if prompt_version:
            prompt_versions.add(prompt_version)
        difficulty = record.get("difficulty") or {}
        if difficulty.get("rubric_id"):
            key = (difficulty.get("rubric_id"), difficulty.get("rubric_version"))
            item = rubric_versions.setdefault(
                key,
                {
                    "rubric_id": difficulty.get("rubric_id"),
                    "version": difficulty.get("rubric_version"),
                },
            )
            for field, value in (
                ("sha256", difficulty.get("rubric_sha256")),
                (
                    "assessment_conditions_version",
                    difficulty.get("assessment_conditions_version"),
                ),
            ):
                if value and field not in item:
                    item[field] = value

    manifest["prompt_versions"] = sorted(prompt_versions)
    manifest["rubric_versions"] = list(rubric_versions.values())
    manifest["finished_at"] = datetime.now(UTC).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--domain", choices=DOMAIN_CHOICES, default="code")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--set",
        choices=SET_CHOICES,
        default="all",
        dest="case_set",
        help="math prompt set (code has only natural cases)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        help="total authoring jobs (default: five for code, the selected set for math)",
    )
    parser.add_argument("--correction-drill", action="store_true")
    args = parser.parse_args()

    if args.correction_drill and args.domain != "code":
        parser.error("--correction-drill is only available for the code domain")
    if args.env_file:
        load_dotenv(args.env_file)

    cases_version, cases = _cases_for(args.domain, args.case_set)
    if not cases:
        parser.error(f"--set {args.case_set} has no {args.domain} cases")

    jobs = args.jobs
    if jobs is None:
        if args.correction_drill:
            jobs = 1
        elif args.domain == "code":
            jobs = 5
        else:
            jobs = len(cases)
    if jobs < 1:
        parser.error("--jobs must be at least one")
    if args.correction_drill:
        cases = cases[:1]

    requested_sets = [cases[index % len(cases)]["set"] for index in range(jobs)]
    domain = create_domain(args.domain)
    revision = source_revision()
    manifest = {
        **revision,
        "validator_revision": revision["git_revision"],
        "cases_version": cases_version,
        "domain": args.domain,
        "case_set": args.case_set,
        "started_at": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "requested_model": args.model,
        "resolved_model": None,
        "provider_settings": None,
        "requested_jobs": jobs,
        "controlled_failure_injection": args.correction_drill,
        "preview_seeds": PREVIEW_SEEDS,
        **_domain_versions(args.domain),
        "cases": [
            {
                "id": case["id"],
                "set": case["set"],
                "difficulty": case["difficulty"],
                "prompt": case["prompt"],
            }
            for case in cases
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir = args.output.with_suffix("")
    artifact_dir.mkdir(exist_ok=True)
    manifest_path = args.output.with_suffix(".manifest.json")
    write_json(manifest_path, manifest)
    summary_path = args.output.with_suffix(".summary.json")
    records = []
    write_json(summary_path, summarize_records(records, jobs, requested_sets))
    with args.output.open("w") as output:
        for index in range(jobs):
            case = cases[index % len(cases)]
            case_id = case["id"]
            job_id = f"{index + 1:03d}-{case_id}"
            request = domain.request_model(
                prompt=case["prompt"], difficulty=case["difficulty"]
            )
            record = {
                "job_id": job_id,
                "case_id": case_id,
                "case_set": case["set"],
                "domain": args.domain,
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
                record["provider_settings"] = provider.generation_settings()
                catalogue_path = artifact_dir / f"{job_id}.catalogue.json"

                def save_catalogue(snapshot, path=catalogue_path, job_record=record):
                    write_json(path, {"tools": snapshot.definitions()})
                    job_record["catalogue_file"] = path.name

                result = TemplateApplication().author_template(
                    request,
                    domain=domain,
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
            finally:
                close_provider(provider)

            record["duration_ms"] = (time.perf_counter() - started) * 1000

            if result is not None and result.artifact is not None:
                try:
                    artifact_path = artifact_dir / f"{job_id}.template.json"
                    artifact_path.write_text(
                        result.artifact.model_dump_json(indent=2) + "\n"
                    )

                    loaded = domain.validated_model.model_validate_json(
                        artifact_path.read_text()
                    )
                    app = TemplateApplication()
                    previews = []
                    for seed in PREVIEW_SEEDS:
                        original = app.generate_question(
                            result.artifact, domain=domain, seed=seed
                        )
                        replay = app.generate_question(loaded, domain=domain, seed=seed)
                        replay_again = app.generate_question(
                            loaded, domain=domain, seed=seed
                        )
                        if not original == replay == replay_again:
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

            authoring_result = record.get("authoring_result") or {}
            record["outcome"] = _outcome_for_status(record["status"])
            record["checked"] = record["status"] == "checked"
            record["needs_review"] = record["status"] == "needs_review"
            record["failed"] = record["status"] == "error"
            record["unresolved"] = False
            record["attempts_used"] = len(authoring_result.get("attempts", []))
            record["failed_check_codes_by_attempt"] = _attempt_failure_codes(
                authoring_result
            )
            record["difficulty"] = _difficulty_record(authoring_result)
            record["relevance"] = _relevance_record(authoring_result)
            (
                record["examples_checked"],
                record["declared_domain_size"],
            ) = _coverage(authoring_result)
            record["author_tokens"] = _author_tokens(authoring_result)
            record["judge_tokens"] = _judge_tokens(authoring_result)

            print(json.dumps(record), file=output, flush=True)
            records.append(record)

            summary = summarize_records(records, jobs, requested_sets)
            write_json(summary_path, summary)
            _update_manifest(manifest, records)
            write_json(manifest_path, manifest)
            print(
                json.dumps(
                    {
                        "job_id": job_id,
                        "status": record["status"],
                        "outcome": record["outcome"],
                        "attempts": record["attempts_used"],
                        "seconds": round(record["duration_ms"] / 1000, 3),
                        "reason": authoring_result.get("reason", record.get("error")),
                    }
                ),
                flush=True,
            )
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["checked"] == jobs and not summary["replay_failed_jobs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
