from pathlib import Path

import pytest

from edcraft_validator.application import QuestionTemplateApplication, TemplateEvaluator
from edcraft_validator.domains.code.templates import (
    CodeQuestionTemplate,
    CodeTemplateProposal,
    TemplateValidator,
)
from edcraft_validator.executor import DockerExecutor
from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplatePromptMetadata,
)

TEMPLATE_PATHS = sorted(
    (Path(__file__).parents[1] / "examples" / "templates").glob("*.json")
)


@pytest.mark.docker
def test_valid_example_executes_in_docker() -> None:
    result = DockerExecutor().execute(
        "def square(x):\n    return x * x",
        "square",
        {"x": 4},
        timeout_seconds=2,
    )

    assert result.ok
    assert result.answer == 16


@pytest.mark.docker
def test_generated_code_is_bounded_inside_docker() -> None:
    # Either deterministic worker guard may win, but Docker OOM must not win.
    result = DockerExecutor().execute(
        "def slow(value):\n"
        "    for _ in range(1000000000):\n"
        "        pass\n"
        "    return value",
        "slow",
        {"value": 1},
        timeout_seconds=0.01,
    )

    # Require a worker-level guard to stop execution before Docker's memory ceiling.
    assert not result.ok
    assert result.error_code in {"EXECUTION_TIMEOUT", "TRACE_LIMIT_EXCEEDED"}


@pytest.mark.docker
def test_generated_code_trace_limit_is_enforced_inside_docker() -> None:
    result = DockerExecutor().execute(
        "def expensive(value):\n"
        "    for _ in range(1000000000):\n"
        "        value += 1\n"
        "    return value",
        "expensive",
        {"value": 1},
        timeout_seconds=10,
    )

    assert not result.ok
    assert result.error_code == "TRACE_LIMIT_EXCEEDED"


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
        provider = "stub"
        model = "stub-model"

        def prompt_metadata(self, request):
            return TemplatePromptMetadata(version="test-v1", sha256="b" * 64)

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

    report = TemplateEvaluator(
        generator_factory=lambda selection: StubGenerator()
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("beginner",),
        repetitions=1,
    )
    assert report.summary.approved == 1
    assert report.attempts[0].approved_template is not None
