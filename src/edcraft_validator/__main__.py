import json
import sys
from pathlib import Path

from pydantic import ValidationError

from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m edcraft_validator QUESTION.json", file=sys.stderr)
        return 2

    try:
        raw = Path(sys.argv[1]).read_text(encoding="utf-8")
        question = GeneratedQuestion.model_validate_json(raw)
    except (OSError, ValidationError, ValueError) as exc:
        print(json.dumps({"status": "invalid_schema", "error": str(exc)}, indent=2))
        return 1

    report = QuestionValidator().validate(question)
    print(report.model_dump_json(indent=2))
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

