import argparse
from pathlib import Path

from dotenv import load_dotenv

from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.openai import OpenAIQuestionGenerator
from edcraft_validator.generation.service import (
    DEFAULT_ATTEMPT_LOG,
    GenerationService,
)
from edcraft_validator.validator import QuestionValidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the generation pipeline")
    parser.add_argument("--provider", choices=["fake", "openai"], default="fake")
    parser.add_argument(
        "--topic",
        required=True,
        choices=["arithmetic", "conditionals", "loops", "functions", "lists"],
    )
    parser.add_argument(
        "--difficulty",
        required=True,
        choices=["beginner", "intermediate", "advanced"],
    )
    parser.add_argument("--num-distractors", type=int, default=3)
    parser.add_argument("--examples-dir", type=Path, default=Path("examples"))
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()

    load_dotenv()

    request = GenerationRequest(
        topic=args.topic,
        difficulty=args.difficulty,
        num_distractors=args.num_distractors,
    )
    generator = (
        FakeQuestionGenerator(args.examples_dir)
        if args.provider == "fake"
        else OpenAIQuestionGenerator()
    )
    service = GenerationService(
        generator,
        QuestionValidator(),
        attempt_log_path=None if args.no_log else DEFAULT_ATTEMPT_LOG,
    )
    outcome = service.generate(request)
    print(outcome.model_dump_json(indent=2))
    return 0 if outcome.status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
