import json

import pytest
from authoring_helpers import RequestPendingTools
from fastmcp import FastMCP
from pydantic import BaseModel

from edcraft_validator.application.authoring_contracts import AuthoringFailure
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
                "_meta": {"fastmcp": {"tags": ["domain:example"]}},
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

    class CountingClient(FastMcpToolClient):
        listings = 0

        def list_tools(self):
            self.listings += 1
            return super().list_tools()

    client = CountingClient(create_validation_server(code_execution_tool=SumExecutor()))
    application = TemplateApplication(tool_client=client)
    validated = application.create_validated_template(
        CodeTemplateRequest(prompt="Create an arithmetic question", difficulty="easy"),
        domain=domain,
        provider=StubProvider(),
    )
    instance = application.generate_question(validated, domain=domain, seed=7)

    assert len(provider_calls) == 1
    assert client.listings == 1
    assert instance.seed == 7
    assert instance == application.generate_question(validated, domain=domain, seed=7)
    assert len(execution_calls) == validated.validation.execution_calls
    assert len(provider_calls) == 1
    assert validated.validation.examples_checked == 4
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
    assert (
        validated.authoring.base_prompt_version
        == "code-template-v21-property-based+response-v8-full-candidate"
    )
    assert validated.authoring.domain == "code"
    assert provider_calls[0].tool_catalogue.names == (
        "code_assess_template_difficulty",
        "code_require_features",
        "code_validate_answers_and_distractors",
        "code_verify_template_structure",
    )
    assert "tool_catalogue" not in validated.authoring.model_dump()
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

    @server.tool(
        description="Double a value",
        version="1",
        tags={"domain:example", "domain:math"},
    )
    def double_value(value: int) -> ToolEvidence:
        events.append("tool")
        return ToolEvidence(
            tool="double_value",
            version="1",
            status="passed",
            details={"input": value, "value": value * 2},
        )

    @server.tool(description="Math-only check", version="1", tags={"domain:math"})
    def math_only(value: int) -> ToolEvidence:
        pytest.fail("Another domain's tools must not be offered or executed")

    class ExampleDomain:
        name = "example"

        request_model = ExampleRequest
        candidate_model = ExampleTemplate
        validated_model = ExampleValidated

        def generation_request(self, request):
            from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=PlannedGenerationResponse[ExampleProposal],
                prompt_version="example-v1",
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
            assert request.offered_tool_names == ("double_value",)
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
    assert "request" not in validated.authoring.model_dump()
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

        def tool_bindings(self, request, candidate, tool_name):
            pytest.fail("Generation failures must stop before validation")

    class FailingProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            raise generation_error

    captured_catalogues = []
    with pytest.raises(AuthoringFailure, match=str(generation_error)) as failure:
        TemplateApplication(
            tool_catalogue=ExampleCatalogue()
        ).create_validated_template(
            ExampleRequest(topic="fractions"),
            domain=FailingDomain(),
            provider=FailingProvider(),
            on_catalogue_resolved=captured_catalogues.append,
        )
    assert len(captured_catalogues) == 1
    result = failure.value.result
    assert result.failure.stage == "generation"
    assert result.failure.code == generation_error.category
    assert not result.attempts
    assert result.usage.model_call_count == 1
    assert result.usage.input_tokens is None
    assert result.generation_duration_ms > 0
    assert captured_catalogues[0].names == ("double_value", "positive_value")


def test_unknown_recommended_check_stops_before_candidate_validation() -> None:
    class Domain:
        name = "example"

        def generation_request(self, request):
            from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=PlannedGenerationResponse[ExampleProposal],
                prompt_version="example-v1",
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

    with pytest.raises(
        AuthoringFailure, match="not offered: invented_check"
    ) as failure:
        TemplateApplication(
            tool_catalogue=ExampleCatalogue()
        ).create_validated_template(
            ExampleRequest(topic="fractions"),
            domain=Domain(),
            provider=Provider(),
        )
    assert failure.value.result.failure.code == "schema_validation"
    assert failure.value.result.usage.model_call_count == 1


def test_non_code_domain_can_plan_typed_arguments_without_shared_tool_names():
    from pydantic import ConfigDict, Field

    from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

    class Bounds(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        minimum: int = Field(ge=0)

    server = FastMCP("Example typed plan")

    @server.tool(
        description="Check a chosen bound", version="1", tags={"domain:example"}
    )
    def meets_bound(value: int, minimum: int) -> ToolEvidence:
        assert value == 12 and minimum == 5
        return ToolEvidence(tool="meets_bound", version="1", status="passed")

    class Domain:
        name = "example"

        def generation_request(self, request):
            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=PlannedGenerationResponse[ExampleProposal],
                prompt_version="example-v2",
                check_argument_models=(("meets_bound", Bounds),),
            )

        def build_candidate(self, request, proposal):
            return ExampleTemplate(value=proposal.value)

        def tool_bindings(self, request, candidate, name):
            return {"value": candidate.value}

        def finalize_checked_template(self, candidate, evidence):
            return ExampleValidated(value=candidate.value)

    class Provider:
        provider, model = "stub", "structured-only"

        def generate(self, request):
            return request.response_model.model_validate(
                {
                    "proposal": {"value": 12},
                    "checks": [{"name": "meets_bound", "arguments": {"minimum": 5}}],
                }
            )

    result = TemplateApplication(tool_client=FastMcpToolClient(server)).author_template(
        ExampleRequest(topic="bounds"), domain=Domain(), provider=Provider()
    )
    assert result.status == "checked"
    assert result.check_plan[0].arguments == {"minimum": 5}
    assert result.attempts[0].executions[0].application_arguments == {"value": 12}
    assert result.usage.model_call_count == 1


@pytest.mark.parametrize("replacement", [4, 11])
def test_non_code_full_revision_enforces_domain_constraints_before_checking(
    replacement,
):
    from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

    class Request(BaseModel):
        topic: str
        maximum: int

    checked_values = []
    server = FastMCP("Example full revision")

    @server.tool(description="Check positivity", version="1", tags={"domain:example"})
    def positive(value: int) -> ToolEvidence:
        checked_values.append(value)
        return ToolEvidence(
            tool="positive",
            version="1",
            status="passed" if value > 0 else "failed",
            findings=[]
            if value > 0
            else [{"code": "NONPOSITIVE", "message": "Use a positive value"}],
            details={"value": value},
        )

    class Domain:
        name = "example"

        def generation_request(self, request):
            return StructuredGenerationRequest(
                messages=[{"role": "user", "content": request.topic}],
                response_model=PlannedGenerationResponse[ExampleProposal],
                prompt_version="example-full-revision-v1",
            )

        def build_candidate(self, request, proposal):
            if proposal.value > request.maximum:
                raise ValueError("Candidate exceeds the original request maximum")
            return ExampleTemplate(value=proposal.value)

        def tool_bindings(self, request, candidate, name):
            return {"value": candidate.value}

        def finalize_checked_template(self, candidate, evidence):
            assert evidence[0].details["value"] == candidate.value
            return ExampleValidated(value=candidate.value)

    class Author:
        provider, model = "stub", "full-revision"
        requests = []

        def generate(self, request):
            self.requests.append(request)
            if request.schema_name == "template_revision":
                assert request.response_model is ExampleProposal
                feedback = json.loads(request.messages[-1]["content"])
                assert feedback["latest_candidate"] == {"value": -1}
                assert feedback["author_request"]["maximum"] == 10
                assert feedback["check_results"][0]["evidence"]["status"] == "failed"
                assert feedback["remaining_revisions"] == 3
                return request.response_model(value=replacement)
            return request.response_model.model_validate(
                {
                    "proposal": {"value": -1},
                    "checks": [{"name": "positive", "arguments": {}}],
                }
            )

    author = Author()
    result = TemplateApplication(tool_client=FastMcpToolClient(server)).author_template(
        Request(topic="A positive value no greater than ten", maximum=10),
        domain=Domain(),
        provider=author,
    )
    assert len(author.requests) == 2
    assert result.check_plan[0].model_dump() == {"name": "positive", "arguments": {}}
    if replacement == 4:
        assert result.status == "checked"
        assert checked_values == [-1, 4]
        assert result.artifact.value == 4
        assert len(result.attempts) == 2
    else:
        assert result.status == "error"
        assert result.failure.stage == "template_building"
        assert "original request maximum" in result.reason
        assert checked_values == [-1]
        assert len(result.attempts) == 1 and result.artifact is None
