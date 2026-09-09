import json

import pytest
from pydantic import BaseModel

from edcraft_validator.application import TemplateApplication
from edcraft_validator.domains.code.models import CodeTemplateRequest
from edcraft_validator.domains.code.module import CodeDomain
from edcraft_validator.domains.code.templates import (
    CodeTemplateProposal,
    TemplateValidator,
    generate_code_question,
)
from edcraft_validator.generation.models import ValidatedTemplateArtifact
from edcraft_validator.tools.python_execution import ExecutionResult


class ExampleRequest(BaseModel):
    topic: str


class ExampleProposal(BaseModel):
    value: int


class ExampleTemplate(BaseModel):
    value: int


class ExampleValidated(ValidatedTemplateArtifact):
    value: int


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

    def instance_generator(validated, seed):
        instance_seeds.append(seed)
        return generate_code_question(validated, seed)

    application = TemplateApplication(
        provider_factory=provider_factory,
        domain_factory=lambda _: CodeDomain(
            validator_factory=lambda: TemplateValidator(execution_tool=SumExecutor()),
            instance_generator=instance_generator,
        ),
    )
    validated = application.create_validated_template(
        CodeTemplateRequest(topic="arithmetic", difficulty="beginner"),
        domain="code",
        provider="stub",
        model="stub-model",
    )
    instance = application.generate_question(validated, domain="code", seed=7)

    assert provider_calls == [("stub", "stub-model")]
    assert instance_seeds == [7]
    assert validated.validation.cases_validated == 4
    assert validated.template.topic == "arithmetic"
    assert validated.template.difficulty == "beginner"
    assert validated.template.answer_target == "return_value"
    assert (
        validated.template.question_template == "What value does add({a}, {b}) return?"
    )
    assert validated.template.question_type == "mcq"
    assert validated.authoring is not None
    assert validated.authoring.provider == "stub"
    assert validated.authoring.model == "stub-model"
    assert validated.authoring.base_prompt_version == "code-template-v8"
    assert validated.authoring.domain == "code"
    assert validated.authoring.request["topic"] == "arithmetic"
    assert validated.authoring.generated_at.utcoffset() is not None
    assert validated.authoring.generation_duration_ms >= 0
    assert [item.expression for item in validated.template.distractors] == [
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
        candidate_model = ExampleTemplate
        validated_model = ExampleValidated

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

        def build_candidate(self, request, proposal):
            return ExampleTemplate(value=proposal.value)

        def validate(self, candidate, *, request=None):
            return ExampleValidated(value=candidate.value)

        def generate_question(self, validated, *, seed):
            return ExampleInstance(value=validated.value, seed=seed)

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
    validated = application.create_validated_template(
        ExampleRequest(topic="fractions"),
        domain="example",
        provider="stub",
    )
    instance = application.generate_question(validated, domain="example", seed=5)

    assert validated.value == 12
    assert validated.authoring.domain == "example"
    assert validated.authoring.request == {"topic": "fractions"}
    assert instance == ExampleInstance(value=12, seed=5)


def test_application_rejects_domain_without_shared_validated_contract() -> None:
    class InvalidDomain:
        name = "invalid"

        def validate(self, candidate, *, request=None):
            return ExampleTemplate(value=candidate.value)

    application = TemplateApplication(domain_factory=lambda _: InvalidDomain())

    with pytest.raises(TypeError, match="shared authoring contract"):
        application.validate_template(ExampleTemplate(value=1), domain="invalid")
