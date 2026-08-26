import os
from pathlib import Path

import pytest

from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator

RUN_DOCKER_TESTS = os.environ.get("EDCRAFT_RUN_DOCKER_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_DOCKER_TESTS,
    reason="Set EDCRAFT_RUN_DOCKER_TESTS=1 after building the executor image",
)
def test_valid_example_executes_in_docker() -> None:
    example_path = Path(__file__).parents[1] / "examples" / "valid_square.json"
    question = GeneratedQuestion.model_validate_json(
        example_path.read_text(encoding="utf-8")
    )

    report = QuestionValidator().validate(question)

    assert report.status == "valid", report.model_dump_json(indent=2)
    assert report.actual_answer == 16


@pytest.mark.skipif(
    not RUN_DOCKER_TESTS,
    reason="Set EDCRAFT_RUN_DOCKER_TESTS=1 after building the executor image",
)
def test_generated_code_timeout_is_enforced_inside_docker() -> None:
    question = GeneratedQuestion.model_validate(
        {
            "code": [
                "def slow(value):",
                "    for _ in range(1000000000):",
                "        value += 1",
                "    return value",
            ],
            "entry_function": "slow",
            "inputs": {"value": 1},
            "question": "What value does slow(1) return?",
            "proposed_answer": 1,
            "distractors": [2, 3],
            "question_type": "mcq",
        }
    )

    # Stop quickly enough that trace records cannot reach the memory limit first.
    report = QuestionValidator(timeout_seconds=0.01).validate(question)

    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_TIMEOUT"
