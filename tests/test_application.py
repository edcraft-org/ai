from edcraft_validator.application import QuestionTemplateApplication
from edcraft_validator.domains.code.templates import (
    CodeTemplateProposal,
    TemplateValidator,
)
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.models import TemplateAuthoringRequest


def test_template_application_authors_once_then_generates_locally() -> None:
    proposal = CodeTemplateProposal.model_validate(
        {
            "code": "def add(a, b):\n    return a + b",
            "entry_function": "add",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [5, 6]},
            ],
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a - b", "reason_template": "Subtracts."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
            ],
        }
    )
    provider_calls: list[str] = []

    class StubTemplateGenerator:
        def generate_proposal(self, request):
            return proposal

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
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner"),
        provider="stub",
    )
    instance = application.generate(approved, seed=7)

    assert provider_calls == ["stub"]
    assert approved.validation.cases_validated == 4
    assert approved.template.topic == "arithmetic"
    assert approved.template.difficulty == "beginner"
    assert approved.template.answer_target == "return_value"
    assert (
        approved.template.question_template == "What value does add({a}, {b}) return?"
    )
    assert approved.template.question_type == "mcq"
    assert instance.question.proposed_answer == sum(instance.parameters.values())
