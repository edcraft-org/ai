from pathlib import Path

from edcraft_validator.application import (
    QuestionGenerationApplication,
    QuestionTemplateApplication,
)
from edcraft_validator.domains.code.templates import (
    CodeQuestionTemplate,
    TemplateValidator,
)
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import ValidationReport


class StubGenerator:
    provider = "stub"
    model = "stub-model"

    def generate_draft(self, request, *, feedback=None):
        return QuestionDraft(
            code="def square(x):\n    return x * x",
            entry_function="square",
            inputs={"x": 4},
            question="What does square(4) return?",
            distractors=[4, 8, 20],
            distractor_reasons=["reason"] * 3,
        )


class StubValidator:
    def compute_answer(self, question):
        return ValidationReport(status="valid", actual_answer=16)

    def validate(self, question, *, actual_answer=None, trace_summary=None):
        return ValidationReport(status="valid", actual_answer=actual_answer)


def test_application_service_owns_generation_wiring() -> None:
    calls: list[tuple[str, object]] = []

    def generator_factory(provider, *, examples_dir):
        calls.append((provider, examples_dir))
        return StubGenerator()

    application = QuestionGenerationApplication(
        generator_factory=generator_factory,
        validator_factory=StubValidator,
    )

    outcome = application.generate(
        GenerationRequest(topic="arithmetic", difficulty="beginner"),
        provider="stub",
        attempt_log_path=None,
    )

    assert outcome.status == "accepted"
    assert outcome.question is not None
    assert outcome.question.proposed_answer == 16
    assert calls == [("stub", Path("examples"))]


def test_template_application_authors_once_then_generates_locally() -> None:
    template = CodeQuestionTemplate.model_validate(
        {
            "template_id": "arithmetic.sum",
            "version": 1,
            "topic": "arithmetic",
            "difficulty": "beginner",
            "code": "def add(a, b):\n    return a + b",
            "entry_function": "add",
            "parameters": [
                {"name": "a", "values": [1, 2]},
                {"name": "b", "values": [5, 6]},
            ],
            "question_template": "What does add({a}, {b}) return?",
            "answer_target": "return_value",
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a - b", "reason_template": "Subtracts."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
            ],
            "question_type": "mcq",
        }
    )
    provider_calls: list[str] = []

    class StubTemplateGenerator:
        def generate_template(self, request):
            return template

    class SumExecutor:
        def execute(self, code, entry_function, inputs, *, timeout_seconds):
            return ExecutionResult(ok=True, answer=inputs["a"] + inputs["b"])

    def generator_factory(provider):
        provider_calls.append(provider)
        return StubTemplateGenerator()

    application = QuestionTemplateApplication(
        generator_factory=generator_factory,
        validator_factory=lambda: TemplateValidator(executor=SumExecutor()),
    )
    approved = application.author(
        GenerationRequest(topic="arithmetic", difficulty="beginner"),
        provider="stub",
    )
    instance = application.generate(approved, seed=7)

    assert provider_calls == ["stub"]
    assert approved.validation.cases_validated == 4
    assert instance.question.proposed_answer == sum(instance.parameters.values())
