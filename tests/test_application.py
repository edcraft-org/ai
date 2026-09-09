import json

from pydantic import BaseModel

from edcraft_validator.application import TemplateApplication
from edcraft_validator.domains.code.models import CodeTemplateAuthoringRequest
from edcraft_validator.domains.code.module import CodeDomain
from edcraft_validator.domains.code.templates import (
    CodeTemplateProposal,
    TemplateValidator,
    generate_template_instance,
)
from edcraft_validator.tools.python_execution import ExecutionResult


class ExampleRequest(BaseModel):
    topic: str


class ExampleProposal(BaseModel):
    value: int


class ExampleTemplate(BaseModel):
    value: int


class ExampleApproved(BaseModel):
    value: int
    authoring: object | None = None


class ExampleInstance(BaseModel):
    value: int
    seed: int


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

    class StubProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return proposal

    class SumExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=item["a"] + item["b"])
                for item in inputs
            ]

    def provider_factory(selection):
        provider_calls.append((selection.provider, selection.model))
        return StubProvider()

    def instance_generator(approved, seed):
        instance_seeds.append(seed)
        return generate_template_instance(approved, seed)

    application = TemplateApplication(
        provider_factory=provider_factory,
        domain_factory=lambda _: CodeDomain(
            validator_factory=lambda: TemplateValidator(execution_tool=SumExecutor()),
            instance_generator=instance_generator,
        ),
    )
    approved = application.author(
        CodeTemplateAuthoringRequest(topic="arithmetic", difficulty="beginner"),
        domain="code",
        provider="stub",
        model="stub-model",
    )
    instance = application.generate(approved, domain="code", seed=7)

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
    assert approved.authoring.prompt.version == "code-template-v8"
    assert approved.authoring.domain == "code"
    assert approved.authoring.request["topic"] == "arithmetic"
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


def test_application_can_run_a_non_code_domain_without_provider_changes() -> None:
    class ExampleDomain:
        name = "example"
        template_model = ExampleTemplate
        approved_model = ExampleApproved

        def generation_request(self, request, *, provider):
            from edcraft_validator.generation.base import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=ExampleProposal,
                parse_response=lambda content: ExampleProposal.model_validate_json(
                    content
                ),
                prompt_version="example-v1",
            )

        def build_template(self, request, proposal):
            return ExampleTemplate(value=proposal.value)

        def approve(self, template, *, request=None):
            return ExampleApproved(value=template.value)

        def generate(self, approved, *, seed):
            return ExampleInstance(value=approved.value, seed=seed)

    class ExampleProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            assert request.response_model is ExampleProposal
            return request.parse_response(json.dumps({"value": 12}))

    application = TemplateApplication(
        provider_factory=lambda selection: ExampleProvider(),
        domain_factory=lambda name: ExampleDomain(),
    )
    approved = application.author(
        ExampleRequest(topic="fractions"),
        domain="example",
        provider="stub",
    )
    instance = application.generate(approved, domain="example", seed=5)

    assert approved.value == 12
    assert approved.authoring.domain == "example"
    assert approved.authoring.request == {"topic": "fractions"}
    assert instance == ExampleInstance(value=12, seed=5)
