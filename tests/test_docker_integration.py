from pathlib import Path

import pytest

from edcraft_validator.application import QuestionTemplateApplication
from edcraft_validator.domains.code.templates import (
    CodeQuestionTemplate,
    CodeTemplateProposal,
    TemplateValidator,
)
from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator

TEMPLATE_PATHS = sorted(
    (Path(__file__).parents[1] / "examples" / "templates").glob("*.json")
)


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
def test_generated_code_is_bounded_inside_docker() -> None:
    # Either deterministic worker guard may win, but Docker OOM must not win.
    question = GeneratedQuestion.model_validate(
        {
            "code": [
                "def slow(value):",
                "    for _ in range(1000000000):",
                "        pass",
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

    # Require a worker-level guard to stop execution before Docker's memory ceiling.
    report = QuestionValidator(timeout_seconds=0.01).validate(question)

    assert report.status == "execution_error"
    assert report.issues[0].code in {"EXECUTION_TIMEOUT", "TRACE_LIMIT_EXCEEDED"}


@pytest.mark.docker
def test_generated_code_trace_limit_is_enforced_inside_docker() -> None:
    question = GeneratedQuestion.model_validate(
        {
            "code": [
                "def expensive(value):",
                "    for _ in range(1000000000):",
                "        value += 1",
                "    return value",
            ],
            "entry_function": "expensive",
            "inputs": {"value": 1},
            "question": "What value does expensive(1) return?",
            "proposed_answer": 1,
            "distractors": [2, 3],
            "question_type": "mcq",
        }
    )

    report = QuestionValidator(timeout_seconds=10).validate(question)

    assert report.status == "execution_error"
    assert report.issues[0].code == "TRACE_LIMIT_EXCEEDED"


@pytest.mark.docker
@pytest.mark.parametrize("template_path", TEMPLATE_PATHS, ids=lambda path: path.stem)
def test_template_is_exhaustively_approved_in_docker(template_path: Path) -> None:
    template = CodeQuestionTemplate.model_validate_json(template_path.read_text())

    approved = TemplateValidator().validate(template)

    expected_cases = 1
    for parameter in template.parameters:
        expected_cases *= len(parameter.values)
    assert approved.validation.cases_validated == expected_cases


@pytest.mark.docker
def test_model_proposal_is_normalized_then_approved_in_docker() -> None:
    path = (
        Path(__file__).parents[1] / "examples" / "templates" / "arithmetic_linear.json"
    )
    canonical = CodeQuestionTemplate.model_validate_json(path.read_text())
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "code",
                "entry_function",
                "parameters",
                "answer_expression",
                "distractors",
            }
        )
    )

    class StubGenerator:
        def generate_proposal(self, request):
            return proposal

    application = QuestionTemplateApplication(
        generator_factory=lambda provider: StubGenerator()
    )
    approved = application.author(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner"),
        provider="stub",
    )

    assert approved.template.question_template == (
        "What value does calculate({a}, {b}, {c}) return?"
    )
    expected_cases = 1
    for parameter in proposal.parameters:
        expected_cases *= len(parameter.values)
    assert approved.validation.cases_validated == expected_cases
