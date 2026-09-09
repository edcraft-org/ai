from pathlib import Path

import pytest

from edcraft_validator.application import TemplateApplication
from edcraft_validator.domains.code.evaluation import TemplateEvaluator
from edcraft_validator.domains.code.models import CodeTemplateRequest
from edcraft_validator.domains.code.module import CodeDomain
from edcraft_validator.domains.code.templates import (
    CodeTemplateCandidate,
    CodeTemplateProposal,
    TemplateValidator,
)
from edcraft_validator.tools.python_execution import LocalPythonTool

TEMPLATE_PATHS = sorted(
    (Path(__file__).parents[1] / "examples" / "templates").glob("*.json")
)


def test_valid_example_executes_with_local_python_tool() -> None:
    result = LocalPythonTool().execute_batch(
        "def square(x):\n    return x * x",
        "square",
        [{"x": 4}],
        timeout_seconds=2,
    )[0]

    assert result.ok
    assert result.answer == 16


def test_generated_code_is_bounded_by_local_python_tool() -> None:
    result = LocalPythonTool().execute_batch(
        "def slow(value):\n"
        "    for _ in range(1000000000):\n"
        "        pass\n"
        "    return value",
        "slow",
        [{"value": 1}],
        timeout_seconds=0.01,
    )[0]

    assert not result.ok
    assert result.error_code in {"EXECUTION_TIMEOUT", "TRACE_LIMIT_EXCEEDED"}


def test_generated_code_trace_limit_is_enforced() -> None:
    result = LocalPythonTool().execute_batch(
        "def expensive(value):\n"
        "    for _ in range(1000000000):\n"
        "        value += 1\n"
        "    return value",
        "expensive",
        [{"value": 1}],
        timeout_seconds=10,
    )[0]

    assert not result.ok
    assert result.error_code == "TRACE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("template_path", TEMPLATE_PATHS, ids=lambda path: path.stem)
def test_template_is_exhaustively_validated(template_path: Path) -> None:
    template = CodeTemplateCandidate.model_validate_json(template_path.read_text())

    validated = TemplateValidator().validate(template)

    expected_cases = 1
    for parameter in template.parameters:
        expected_cases *= len(parameter.values)
    assert validated.validation.cases_validated == expected_cases


def test_model_proposal_is_built_then_validated() -> None:
    path = (
        Path(__file__).parents[1] / "examples" / "templates" / "arithmetic_linear.json"
    )
    canonical = CodeTemplateCandidate.model_validate_json(path.read_text())
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

    class StubProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return proposal

    application = TemplateApplication(
        provider_factory=lambda selection: StubProvider(),
        domain_factory=lambda name: CodeDomain(),
    )
    validated = application.create_validated_template(
        CodeTemplateRequest(topic="arithmetic", difficulty="beginner"),
        domain="code",
        provider="stub",
    )

    assert validated.template.question_template == (
        "What value does calculate({a}, {b}, {c}) return?"
    )
    expected_cases = 1
    for parameter in proposal.parameters:
        expected_cases *= len(parameter.values)
    assert validated.validation.cases_validated == expected_cases

    report = TemplateEvaluator(
        provider_factory=lambda selection: StubProvider()
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("beginner",),
        repetitions=1,
    )
    assert report.summary.validated == 1
    assert report.attempts[0].validated_template is not None
