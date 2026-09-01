import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.registry import available_providers, create_generator
from edcraft_validator.generation.service import (
    DEFAULT_ATTEMPT_LOG,
    GenerationService,
)
from edcraft_validator.validator import QuestionValidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the generation pipeline")
    parser.add_argument(
        "--provider",
        choices=available_providers(),
        required=True,
    )
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
    generator = create_generator(args.provider, examples_dir=args.examples_dir)
    service = GenerationService(
        generator,
        QuestionValidator(),
        attempt_log_path=None if args.no_log else DEFAULT_ATTEMPT_LOG,
    )
    outcome = service.generate(request)
    output = outcome.model_dump(mode="json")
    for attempt in output["attempts"]:
        attempt.pop("distractor_reasons", None)
    print(json.dumps(output, indent=2))
    return 0 if outcome.status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
