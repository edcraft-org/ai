from pathlib import Path

import pytest

from edcraft_validator.domains.code.templates import (
    CodeQuestionTemplate,
    TemplateValidator,
)
from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator


@pytest.mark.docker
def test_valid_example_executes_in_docker() -> None:
    # The documented fixture should validate through the real Docker boundary.
    example_path = Path(__file__).parents[1] / "examples" / "valid_square.json"
    question = GeneratedQuestion.model_validate_json(
        example_path.read_text(encoding="utf-8")
    )

    report = QuestionValidator().validate(question)

    assert report.status == "valid", report.model_dump_json(indent=2)
    assert report.actual_answer == 16


@pytest.mark.docker
def test_generated_code_timeout_is_enforced_inside_docker() -> None:
    # Docker execution must enforce timeouts for expensive generated programs.
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


@pytest.mark.docker
@pytest.mark.parametrize(
    ("template_name", "expected_cases"),
    [("arithmetic_linear.json", 8), ("loop_iterations.json", 3)],
)
def test_template_is_exhaustively_approved_in_docker(
    template_name: str, expected_cases: int
) -> None:
    template_path = Path(__file__).parents[1] / "examples" / "templates" / template_name
    template = CodeQuestionTemplate.model_validate_json(template_path.read_text())

    approved = TemplateValidator().validate(template)

    assert approved.validation.cases_validated == expected_cases
