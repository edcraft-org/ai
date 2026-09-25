import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateProposal,
    CodeTemplateRequest,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    RecommendedCheck,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationSchemaError,
)
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.validation.validation_contracts import (
    CheckResult,
    ValidationFailure,
    ValidationPlan,
    ValidationPolicy,
)


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


class PositiveValueCheck:
    name = "positive_value"
    assurance = "bounded"

    def run(self, context):
        return CheckResult(status="passed" if context.value > 0 else "failed")


def example_plan(candidate):
    return ValidationPlan(
        context=candidate,
        checks=(PositiveValueCheck(),),
        policy=ValidationPolicy(frozenset({"positive_value"})),
    )


def test_template_application_authors_once_then_generates_locally() -> None:
    proposal = CodeTemplateProposal.model_validate(
        {
            "question_template": "What value does add({a}, {b}) return?",
            "code": "def add(a, b):\n    return a + b",
            "entry_function": "add",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [5, 6]},
            ],
            "answer_target": "return_value",
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
    provider_calls = []
    execution_calls: list[str] = []

    class StubProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            provider_calls.append(request)
            return PlannedGenerationResponse(
                proposal=proposal,
                checks=[RecommendedCheck(name="code_execution", arguments={})],
            )

    class SumExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            execution_calls.append(code)
            return [
                ExecutionResult(ok=True, answer=item["a"] + item["b"])
                for item in inputs
            ]

    domain = CodeDomain(execution_tool=SumExecutor())
    application = TemplateApplication()
    validated = application.create_validated_template(
        CodeTemplateRequest(
            prompt="Create an arithmetic question", difficulty="beginner"
        ),
        domain=domain,
        provider=StubProvider(),
    )
    instance = application.generate_question(validated, domain=domain, seed=7)

    assert len(provider_calls) == 1
    assert instance.seed == 7
    assert instance == application.generate_question(validated, domain=domain, seed=7)
    assert len(execution_calls) == 1
    assert len(provider_calls) == 1
    assert validated.validation.cases_validated == 4
    assert validated.template.topic is None
    assert validated.template.difficulty == "beginner"
    assert validated.template.answer_target == "return_value"
    assert (
        validated.template.question_template == "What value does add({a}, {b}) return?"
    )
    assert validated.template.question_type == "mcq"
    assert validated.authoring is not None
    assert validated.authoring.provider == "stub"
    assert validated.authoring.model == "stub-model"
    assert validated.authoring.base_prompt_version == "code-template-v9+response-v3"
    assert validated.authoring.domain == "code"
    assert validated.authoring.request["prompt"] == "Create an arithmetic question"
    assert validated.authoring.request["difficulty"] == "beginner"
    assert [check.name for check in validated.authoring.recommended_checks] == [
        "code_execution"
    ]
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
    events = []

    @dataclass
    class ExampleContext:
        candidate: ExampleTemplate
        checked_value: int | None = None

    class ExampleTool:
        def double(self, value):
            events.append("tool")
            return value * 2

    class DoublingCheck:
        name = "double_value"
        assurance = "exhaustive"

        def __init__(self, tool):
            self.tool = tool

        def run(self, context):
            events.append("check")
            context.checked_value = self.tool.double(context.candidate.value)
            return CheckResult(details={"input": context.candidate.value})

    class ExampleDomain:
        name = "example"
        request_model = ExampleRequest
        candidate_model = ExampleTemplate
        validated_model = ExampleValidated

        def __init__(self, tool):
            self.tool = tool

        def generation_request(self, request):
            from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=PlannedGenerationResponse[ExampleProposal],
                prompt_version="example-v1",
                offered_tool_names=("double_value",),
            )

        def build_candidate(self, request, proposal):
            events.append("build")
            return ExampleTemplate(value=proposal.value)

        def prepare_validation(self, candidate, *, request=None):
            events.append("plan")
            return ValidationPlan(
                context=ExampleContext(candidate),
                checks=(DoublingCheck(self.tool),),
                policy=ValidationPolicy(frozenset({"double_value"})),
            )

        def finalize_template(self, context, report):
            events.append("finalize")
            assert report.accepted
            assert report.evidence[0].details == {"input": 12}
            return ExampleValidated(value=context.checked_value)

        def generate_question(self, validated, *, seed):
            events.append("question")
            return ExampleInstance(value=validated.value, seed=seed)

    class ExampleProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            events.append("generate")
            assert request.response_model == PlannedGenerationResponse[ExampleProposal]
            return request.response_model.model_validate_json(
                json.dumps(
                    {
                        "proposal": {"value": 12},
                        "checks": [{"name": "double_value", "arguments": {}}],
                    }
                )
            )

    domain = ExampleDomain(ExampleTool())
    application = TemplateApplication()
    validated = application.create_validated_template(
        ExampleRequest(topic="fractions"),
        domain=domain,
        provider=ExampleProvider(),
    )
    instance = application.generate_question(validated, domain=domain, seed=5)

    assert events == [
        "generate",
        "build",
        "plan",
        "check",
        "tool",
        "finalize",
        "question",
    ]
    assert validated.value == 24
    assert validated.authoring.domain == "example"
    assert validated.authoring.request == {"topic": "fractions"}
    assert instance == ExampleInstance(value=24, seed=5)


@pytest.mark.parametrize(
    "generation_error",
    [
        GenerationResponseError("malformed JSON"),
        GenerationSchemaError("schema mismatch"),
    ],
)
def test_generation_failures_stop_before_candidate_building_and_validation(
    generation_error,
) -> None:
    class FailingDomain:
        name = "example"

        def generation_request(self, request):
            from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=ExampleProposal,
                prompt_version="example-v1",
            )

        def build_candidate(self, request, proposal):
            pytest.fail("Generation failures must stop before candidate construction")

        def prepare_validation(self, candidate, *, request=None):
            pytest.fail("Generation failures must stop before validation")

    class FailingProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            raise generation_error

    with pytest.raises(type(generation_error), match=str(generation_error)):
        TemplateApplication().create_validated_template(
            ExampleRequest(topic="fractions"),
            domain=FailingDomain(),
            provider=FailingProvider(),
        )


def test_unknown_recommended_check_stops_before_candidate_validation() -> None:
    class Domain:
        name = "example"

        def generation_request(self, request):
            from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=PlannedGenerationResponse[ExampleProposal],
                prompt_version="example-v1",
                offered_tool_names=("positive_value",),
            )

        def build_candidate(self, request, proposal):
            pytest.fail(
                "Unknown recommended checks must stop before candidate building"
            )

        def prepare_validation(self, candidate, *, request=None):
            pytest.fail("Unknown recommended checks must stop before validation")

    class Provider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return PlannedGenerationResponse(
                proposal=ExampleProposal(value=1),
                checks=[RecommendedCheck(name="invented_check", arguments={})],
            )

    with pytest.raises(GenerationSchemaError, match="not offered: invented_check"):
        TemplateApplication().create_validated_template(
            ExampleRequest(topic="fractions"),
            domain=Domain(),
            provider=Provider(),
        )


def test_application_rejects_domain_without_shared_validated_contract() -> None:
    class InvalidDomain:
        name = "invalid"

        def prepare_validation(self, candidate, *, request=None):
            return example_plan(candidate)

        def finalize_template(self, context, report):
            return ExampleTemplate(value=context.value)

    application = TemplateApplication()

    with pytest.raises(TypeError, match="shared authoring contract"):
        application.validate_template(ExampleTemplate(value=1), domain=InvalidDomain())


def test_application_does_not_finalize_rejected_candidate():
    class ExampleDomain:
        name = "example"

        def prepare_validation(self, candidate, *, request=None):
            return example_plan(candidate)

        def finalize_template(self, context, report):
            pytest.fail("Rejected candidates must never be finalized")

    application = TemplateApplication()
    with pytest.raises(ValidationFailure) as error:
        application.validate_template(ExampleTemplate(value=-1), domain=ExampleDomain())
    assert error.value.evidence[0].check == "positive_value"
    assert error.value.evidence[0].status == "failed"
