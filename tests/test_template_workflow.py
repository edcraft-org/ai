import json

import pytest
from authoring_helpers import RequestPendingTools
from fastmcp import FastMCP
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
from edcraft_validator.mcp.catalogue import FastMcpToolCatalogue
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.evidence import ToolEvidence
from edcraft_validator.mcp.server import create_validation_server
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


class ExampleCatalogue:
    def list_tools(self):
        return [
            {
                "name": name,
                "description": f"Check {name}",
                "inputSchema": {"type": "object"},
                "outputSchema": {"type": "object"},
            }
            for name in ("double_value", "positive_value")
        ]


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

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            provider_calls.append(request)
            return PlannedGenerationResponse(
                proposal=proposal,
                checks=[
                    RecommendedCheck(
                        name="code_validate_answers_and_distractors", arguments={}
                    )
                ],
            )

    class SumExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            execution_calls.append(code)
            return [
                ExecutionResult(ok=True, answer=item["a"] + item["b"])
                for item in inputs
            ]

    domain = CodeDomain()

    class CountingCatalogue:
        calls = 0

        def list_tools(self):
            self.calls += 1
            return FastMcpToolCatalogue().list_tools()

    catalogue = CountingCatalogue()
    application = TemplateApplication(
        tool_catalogue=catalogue,
        tool_client=FastMcpToolClient(
            create_validation_server(code_execution_tool=SumExecutor())
        ),
    )
    validated = application.create_validated_template(
        CodeTemplateRequest(prompt="Create an arithmetic question", difficulty="easy"),
        domain=domain,
        provider=StubProvider(),
    )
    instance = application.generate_question(validated, domain=domain, seed=7)

    assert len(provider_calls) == 1
    assert catalogue.calls == 1
    assert instance.seed == 7
    assert instance == application.generate_question(validated, domain=domain, seed=7)
    assert len(execution_calls) == 1
    assert len(provider_calls) == 1
    assert validated.validation.cases_validated == 4
    assert validated.template.topic is None
    assert validated.template.difficulty == "easy"
    assert validated.template.answer_target == "return_value"
    assert (
        validated.template.question_template == "What value does add({a}, {b}) return?"
    )
    assert validated.template.question_type == "mcq"
    assert validated.authoring is not None
    assert validated.authoring.provider == "stub"
    assert validated.authoring.model == "stub-model"
    assert validated.authoring.base_prompt_version == "code-template-v13+response-v3"
    assert validated.authoring.domain == "code"
    assert validated.authoring.request["prompt"] == "Create an arithmetic question"
    assert validated.authoring.request["difficulty"] == "easy"
    assert validated.authoring.fixed_plan == ["code_validate_answers_and_distractors"]
    assert list(provider_calls[0].tool_catalogue.names) == list(
        domain.allowed_tool_names
    )
    assert (
        validated.authoring.tool_catalogue
        == provider_calls[0].tool_catalogue.definitions()
    )
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

    server = FastMCP("Example")

    @server.tool(description="Double a value", version="1")
    def double_value(value: int) -> ToolEvidence:
        events.append("tool")
        return ToolEvidence(
            tool="double_value",
            version="1",
            status="passed",
            details={"input": value, "value": value * 2},
        )

    class ExampleDomain:
        name = "example"
        allowed_tool_names = ("double_value",)
        request_model = ExampleRequest
        candidate_model = ExampleTemplate
        validated_model = ExampleValidated

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

        def tool_bindings(self, request, candidate, tool_name):
            return {"value": candidate.value}

        def finalize_checked_template(self, candidate, evidence):
            events.append("finalize")
            assert evidence[0].details == {"input": 12, "value": 24}
            return ExampleValidated(value=evidence[0].details["value"])

        def generate_question(self, validated, *, seed):
            events.append("question")
            return ExampleInstance(value=validated.value, seed=seed)

    class ExampleProvider(RequestPendingTools):
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

    domain = ExampleDomain()
    application = TemplateApplication(tool_client=FastMcpToolClient(server))
    validated = application.create_validated_template(
        ExampleRequest(topic="fractions"),
        domain=domain,
        provider=ExampleProvider(),
    )
    instance = application.generate_question(validated, domain=domain, seed=5)

    assert events == [
        "generate",
        "build",
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
        allowed_tool_names = ("positive_value",)

        def generation_request(self, request):
            from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=ExampleProposal,
                prompt_version="example-v1",
            )

        def build_candidate(self, request, proposal):
            pytest.fail("Generation failures must stop before candidate construction")

        def tool_bindings(self, request, candidate, tool_name):
            pytest.fail("Generation failures must stop before validation")

    class FailingProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            raise generation_error

    captured_catalogues = []
    with pytest.raises(type(generation_error), match=str(generation_error)):
        TemplateApplication(
            tool_catalogue=ExampleCatalogue()
        ).create_validated_template(
            ExampleRequest(topic="fractions"),
            domain=FailingDomain(),
            provider=FailingProvider(),
            on_catalogue_resolved=captured_catalogues.append,
        )
    assert len(captured_catalogues) == 1
    assert captured_catalogues[0].names == ("positive_value",)


def test_unknown_recommended_check_stops_before_candidate_validation() -> None:
    class Domain:
        name = "example"
        allowed_tool_names = ("positive_value",)

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

        def tool_bindings(self, request, candidate, tool_name):
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
        TemplateApplication(
            tool_catalogue=ExampleCatalogue()
        ).create_validated_template(
            ExampleRequest(topic="fractions"),
            domain=Domain(),
            provider=Provider(),
        )
