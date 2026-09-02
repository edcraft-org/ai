"""CLI for one-time template approval and deterministic question expansion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from edcraft_validator.application import QuestionTemplateApplication
from edcraft_validator.domains.code.capabilities import CODE_DIFFICULTIES, CODE_TOPICS
from edcraft_validator.domains.code.templates import (
    ApprovedCodeQuestionTemplate,
    CodeQuestionTemplate,
)
from edcraft_validator.generation.base import GenerationError
from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.registry import available_template_providers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Author, approve, and expand reusable code-question templates"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    author = commands.add_parser("author", help="author and approve one AI template")
    author.add_argument(
        "--provider", choices=available_template_providers(), required=True
    )
    author.add_argument(
        "--model",
        help="provider model name (defaults to the provider environment setting)",
    )
    author.add_argument(
        "--topic",
        choices=CODE_TOPICS,
        required=True,
    )
    author.add_argument(
        "--difficulty",
        choices=CODE_DIFFICULTIES,
        required=True,
    )
    author.add_argument("--num-distractors", type=int, default=3)
    author.add_argument("--output", type=Path)

    validate = commands.add_parser(
        "validate", help="exhaustively approve a raw template JSON file"
    )
    validate.add_argument("template", type=Path)
    validate.add_argument("--output", type=Path)

    generate = commands.add_parser(
        "generate", help="expand an approved template without AI or validation"
    )
    generate.add_argument("template", type=Path)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--output", type=Path)

    args = parser.parse_args()
    load_dotenv()
    application = QuestionTemplateApplication()
    try:
        if args.command == "author":
            request = TemplateAuthoringRequest(
                topic=args.topic,
                difficulty=args.difficulty,
                num_distractors=args.num_distractors,
            )
            result = application.author(
                request, provider=args.provider, model=args.model
            )
        elif args.command == "validate":
            template = CodeQuestionTemplate.model_validate_json(
                args.template.read_text()
            )
            result = application.approve(template)
        else:
            approved = ApprovedCodeQuestionTemplate.model_validate_json(
                args.template.read_text()
            )
            result = application.generate(approved, seed=args.seed)
    except (GenerationError, OSError, ValidationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _write_json(result.model_dump(mode="json"), args.output)
    return 0


def _write_json(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, indent=2)
    if output is None:
        print(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
