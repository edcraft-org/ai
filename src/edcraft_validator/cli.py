"""CLI for template validation and deterministic question expansion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_types import CODE_DIFFICULTIES, CODE_TOPICS
from edcraft_validator.domains.code.template_evaluator import TemplateEvaluator
from edcraft_validator.domains.domain_registry import available_domains, create_domain
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.llm_errors import GenerationError
from edcraft_validator.llm.provider_registry import (
    available_model_providers,
    create_model_provider,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface without executing a command."""
    parser = argparse.ArgumentParser(
        description="Author, validate, and expand reusable code-question templates"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    author = commands.add_parser("author", help="author and validate one AI template")
    author.add_argument("--domain", choices=available_domains(), required=True)
    author.add_argument(
        "--provider", choices=available_model_providers(), required=True
    )
    author.add_argument(
        "--model",
        help="provider model name (defaults to the provider environment setting)",
    )
    author.add_argument(
        "--request-json",
        type=Path,
        help="JSON file containing fields for the selected domain's request model",
    )
    author.add_argument(
        "--topic",
        choices=CODE_TOPICS,
        help="code-domain request topic (cannot be combined with --request-json)",
    )
    author.add_argument(
        "--difficulty",
        choices=CODE_DIFFICULTIES,
        help="code-domain request difficulty (cannot be combined with --request-json)",
    )
    author.add_argument(
        "--num-distractors",
        type=int,
        help="code-domain distractor count (cannot be combined with --request-json)",
    )
    author.add_argument("--output", type=Path)

    validate = commands.add_parser(
        "validate", help="exhaustively validate a raw template JSON file"
    )
    validate.add_argument("--domain", choices=available_domains(), required=True)
    validate.add_argument("template", type=Path)
    validate.add_argument("--output", type=Path)

    generate = commands.add_parser(
        "generate", help="expand a validated template without AI or revalidation"
    )
    generate.add_argument("--domain", choices=available_domains(), required=True)
    generate.add_argument("template", type=Path)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--output", type=Path)

    evaluate = commands.add_parser(
        "evaluate", help="measure real template validation quality and latency"
    )
    evaluate.add_argument("--domain", choices=("code",), required=True)
    evaluate.add_argument(
        "--provider", choices=available_model_providers(), required=True
    )
    evaluate.add_argument("--model")
    evaluate.add_argument("--topic", choices=(*CODE_TOPICS, "all"), default="all")
    evaluate.add_argument(
        "--difficulty", choices=(*CODE_DIFFICULTIES, "all"), default="all"
    )
    evaluate.add_argument("--repetitions", type=int, default=1)
    evaluate.add_argument("--num-distractors", type=int, default=3)
    evaluate.add_argument(
        "--output", type=Path, default=Path(".artifacts/template-evaluation.jsonl")
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv()
    try:
        handlers = {
            "author": _handle_author,
            "validate": _handle_validate,
            "generate": _handle_generate,
            "evaluate": _handle_evaluate,
        }
        return handlers[args.command](args)
    except (GenerationError, OSError, ValidationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _handle_author(args: argparse.Namespace) -> int:
    domain = create_domain(args.domain)
    request_fields = {
        name: value
        for name, value in {
            "topic": args.topic,
            "difficulty": args.difficulty,
            "num_distractors": args.num_distractors,
        }.items()
        if value is not None
    }
    if args.request_json is not None:
        if request_fields:
            flags = ", ".join(f"--{name.replace('_', '-')}" for name in request_fields)
            raise ValueError(
                f"--request-json cannot be combined with request flags: {flags}"
            )
        request = domain.request_model.model_validate_json(
            args.request_json.read_text()
        )
    else:
        request = domain.request_model.model_validate(request_fields)
    provider = create_model_provider(
        TemplateProviderSelection(provider=args.provider, model=args.model)
    )
    result = TemplateApplication().create_validated_template(
        request, domain=domain, provider=provider
    )
    _write_json(result.model_dump(mode="json"), args.output)
    return 0


def _handle_validate(args: argparse.Namespace) -> int:
    domain = create_domain(args.domain)
    candidate = domain.candidate_model.model_validate_json(args.template.read_text())
    result = TemplateApplication().validate_template(candidate, domain=domain)
    _write_json(result.model_dump(mode="json"), args.output)
    return 0


def _handle_generate(args: argparse.Namespace) -> int:
    domain = create_domain(args.domain)
    validated = domain.validated_model.model_validate_json(args.template.read_text())
    result = TemplateApplication().generate_question(
        validated, domain=domain, seed=args.seed
    )
    _write_json(result.model_dump(mode="json"), args.output)
    return 0


def _handle_evaluate(args: argparse.Namespace) -> int:
    topics = CODE_TOPICS if args.topic == "all" else (args.topic,)
    difficulties = CODE_DIFFICULTIES if args.difficulty == "all" else (args.difficulty,)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as output:

        def record_attempt(attempt: Any) -> None:
            print(attempt.model_dump_json(), file=output, flush=True)
            print(
                f"[{attempt.attempt}] {attempt.request.topic}/"
                f"{attempt.request.difficulty}: {attempt.status} "
                f"({attempt.total_duration_ms / 1000:.1f}s)",
                file=sys.stderr,
                flush=True,
            )

        report = TemplateEvaluator().evaluate(
            provider=args.provider,
            model=args.model,
            topics=topics,
            difficulties=difficulties,
            repetitions=args.repetitions,
            num_distractors=args.num_distractors,
            on_attempt=record_attempt,
        )
    print(report.summary.model_dump_json(indent=2))
    return 0 if report.summary.failed == 0 else 1


def _write_json(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, indent=2)
    if output is None:
        print(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
