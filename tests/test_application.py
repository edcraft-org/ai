from edcraft_validator.application import QuestionTemplateApplication
from edcraft_validator.domains.code.templates import (
    CodeTemplateProposal,
    TemplateValidator,
    generate_template_instance,
)
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplatePromptMetadata,
)


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
                {"expression": "a + b", "reason_template": "Repeats answer."},
                {"expression": "a - b", "reason_template": "Subtracts."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
                {"expression": "a + b + 2", "reason_template": "Adds two."},
            ],
        }
    )
    provider_calls: list[tuple[str, str | None]] = []
    instance_seeds: list[int] = []

    class StubTemplateGenerator:
        provider = "stub"
        model = "stub-model"

        def prompt_metadata(self, request):
            return TemplatePromptMetadata(version="test-v1", sha256="a" * 64)

        def generate_proposal(self, request):
            return proposal

    class SumExecutor:
        def execute(self, code, entry_function, inputs, *, timeout_seconds):
            return ExecutionResult(ok=True, answer=inputs["a"] + inputs["b"])

    def generator_factory(selection):
        provider_calls.append((selection.provider, selection.model))
        return StubTemplateGenerator()

    def instance_generator(approved, seed):
        instance_seeds.append(seed)
        return generate_template_instance(approved, seed)

    application = QuestionTemplateApplication(
        generator_factory=generator_factory,
        validator_factory=lambda: TemplateValidator(executor=SumExecutor()),
        instance_generator=instance_generator,
    )
    approved = application.author(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner"),
        provider="stub",
        model="stub-model",
    )
    instance = application.generate(approved, seed=7)

    assert provider_calls == [("stub", "stub-model")]
    assert instance_seeds == [7]
    assert approved.validation.cases_validated == 4
    assert approved.template.topic == "arithmetic"
    assert approved.template.difficulty == "beginner"
    assert approved.template.answer_target == "return_value"
    assert (
        approved.template.question_template == "What value does add({a}, {b}) return?"
    )
    assert approved.template.question_type == "mcq"
    assert approved.authoring is not None
    assert approved.authoring.provider == "stub"
    assert approved.authoring.model == "stub-model"
    assert approved.authoring.prompt.version == "test-v1"
    assert approved.authoring.request.topic == "arithmetic"
    assert approved.authoring.generation_duration_ms >= 0
    assert approved.authoring.validation_duration_ms >= 0
    assert [item.expression for item in approved.template.distractors] == [
        "a - b",
        "a + b + 1",
        "a + b - 1",
    ]
    assert instance.question.proposed_answer == sum(instance.parameters.values())
    assert instance.question.distractor_reasons == [
        "Subtracts.",
        "Adds one.",
        "Subtracts one.",
    ]
