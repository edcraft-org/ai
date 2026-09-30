import json

import pytest
from authoring_helpers import RequestPendingTools
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator import cli as template_cli
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains import domain_registry
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.llm import provider_registry
from edcraft_validator.llm.llm_contracts import (
    CheckPlanResponse,
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.evidence import ToolEvidence


class ExampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lesson: str = Field(min_length=1)


class ExampleProposal(BaseModel):
    value: int


class ExampleCandidate(BaseModel):
    lesson: str
    value: int


class ExampleValidated(ValidatedTemplateArtifact):
    lesson: str
    value: int


class ExampleDomain:
    name = "example"
    allowed_tool_names = ("positive_value",)
    request_model = ExampleRequest
    candidate_model = ExampleCandidate
    validated_model = ExampleValidated

    def generation_request(self, request):
        return StructuredGenerationRequest(
            messages=[{"role": "user", "content": request.lesson}],
            response_model=PlannedGenerationResponse[ExampleProposal],
            prompt_version="example-v1",
            offered_tool_names=("positive_value",),
        )

    def build_candidate(self, request, proposal):
        return ExampleCandidate(lesson=request.lesson, value=proposal.value)

    def tool_bindings(self, request, candidate, tool_name):
        return {"value": candidate.value}

    def finalize_checked_template(self, candidate, evidence):
        assert evidence[0].status == "passed"
        return ExampleValidated(lesson=candidate.lesson, value=candidate.value)

    def validation_request(self, candidate):
        return StructuredGenerationRequest(
            messages=[{"role": "user", "content": candidate.model_dump_json()}],
            response_model=CheckPlanResponse,
            prompt_version="example-validation-v1",
        )

    def generate_question(self, validated, *, seed):
        raise NotImplementedError


class ExampleProvider(RequestPendingTools):
    provider = "example-provider"

    def __init__(self, model):
        self.model = model or "example-model"

    def generate(self, request):
        if request.response_model is CheckPlanResponse:
            return CheckPlanResponse.model_validate(
                {"checks": [{"name": "positive_value", "arguments": {}}]}
            )
        assert request.response_model == PlannedGenerationResponse[ExampleProposal]
        return request.response_model.model_validate(
            {
                "proposal": {"value": 12},
                "checks": [{"name": "positive_value", "arguments": {}}],
            }
        )


@pytest.fixture
def example_registry(monkeypatch):
    provider_models = []

    def create_provider(model):
        provider_models.append(model)
        return ExampleProvider(model)

    monkeypatch.setitem(domain_registry._DOMAIN_FACTORIES, "example", ExampleDomain)
    monkeypatch.setitem(
        provider_registry._MODEL_PROVIDER_FACTORIES,
        "example-provider",
        create_provider,
    )
    server = FastMCP("CLI example")

    @server.tool(description="Check positive values", version="1")
    def positive_value(value: int) -> ToolEvidence:
        assert value > 0
        return ToolEvidence(tool="positive_value", version="1", status="passed")

    monkeypatch.setattr(
        template_cli,
        "TemplateApplication",
        lambda: TemplateApplication(tool_client=FastMcpToolClient(server)),
    )
    return provider_models


def test_generate_cli_passes_domain_without_creating_provider(
    monkeypatch, tmp_path, capsys
):
    from types import SimpleNamespace

    parsed = object()
    calls = []
    source = tmp_path / "template.json"
    source.write_text('{"value": 7}')

    class Model:
        @staticmethod
        def model_validate_json(content):
            assert json.loads(content) == {"value": 7}
            return parsed

    domain = SimpleNamespace(candidate_model=Model, validated_model=Model)

    class Result:
        def model_dump(self, *, mode):
            return {"success": True}

    class Application:
        def generate_question(self, validated, *, domain, seed):
            assert seed == 7
            calls.append((validated, domain))
            return Result()

    def unexpected_provider(*args):
        pytest.fail("Local template commands must not create a model provider")

    monkeypatch.setattr(template_cli, "create_domain", lambda name: domain)
    monkeypatch.setattr(template_cli, "create_model_provider", unexpected_provider)
    monkeypatch.setattr(template_cli, "TemplateApplication", Application)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    args = [
        "edcraft-template",
        "generate",
        "--domain",
        "code",
        str(source),
        "--seed",
        "7",
    ]
    monkeypatch.setattr("sys.argv", args)

    assert template_cli.main() == 0
    assert calls == [(parsed, domain)]
    assert json.loads(capsys.readouterr().out) == {"success": True}


def test_author_cli_uses_registered_domain_request_json_end_to_end(
    example_registry, monkeypatch, tmp_path, capsys
) -> None:
    request_path = tmp_path / "example-request.json"
    request_path.write_text(json.dumps({"lesson": "fractions"}))
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "example",
            "--provider",
            "example-provider",
            "--model",
            "example-test-model",
            "--request-json",
            str(request_path),
        ],
    )

    assert template_cli.main() == 0

    assert example_registry == ["example-test-model"]
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "checked"
    result = result["artifact"]
    assert result["lesson"] == "fractions"
    assert result["value"] == 12
    assert result["authoring"]["domain"] == "example"
    assert result["authoring"]["request"] == {"lesson": "fractions"}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param('{"lesson":', "Invalid JSON", id="malformed-json"),
        pytest.param('{"unknown":"value"}', "lesson", id="invalid-model-fields"),
    ],
)
def test_author_request_json_fails_before_provider_creation(
    content, message, example_registry, monkeypatch, tmp_path, capsys
) -> None:
    request_path = tmp_path / "invalid-request.json"
    request_path.write_text(content)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "example",
            "--provider",
            "example-provider",
            "--request-json",
            str(request_path),
        ],
    )

    assert template_cli.main() == 1
    assert example_registry == []
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "request_flag",
    [
        ("--prompt", "Create an arithmetic question"),
        ("--difficulty", "beginner"),
        ("--num-distractors", "2"),
    ],
)
def test_author_rejects_request_json_with_any_request_flag(
    request_flag, monkeypatch, tmp_path, capsys
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "prompt": "Create a loops question",
                "difficulty": "advanced",
            }
        )
    )

    def unexpected_provider(*args):
        pytest.fail("Conflicting request input must fail before provider creation")

    monkeypatch.setattr(template_cli, "create_model_provider", unexpected_provider)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "code",
            "--provider",
            "ollama",
            "--request-json",
            str(request_path),
            *request_flag,
        ],
    )

    assert template_cli.main() == 1
    assert "--request-json cannot be combined" in capsys.readouterr().err


def test_author_flags_report_missing_code_request_fields_before_provider(
    monkeypatch, capsys
) -> None:
    def unexpected_provider(*args):
        pytest.fail("Invalid request data must fail before provider creation")

    monkeypatch.setattr(template_cli, "create_model_provider", unexpected_provider)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "code",
            "--provider",
            "ollama",
        ],
    )

    assert template_cli.main() == 1
    error = capsys.readouterr().err
    assert "prompt" in error
    assert "difficulty" in error


def test_author_cli_passes_explicit_provider_and_model(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class Result:
        status = "checked"

        def model_dump(self, *, mode: str) -> dict[str, bool]:
            assert mode == "json"
            return {"validated": True}

    class StubApplication:
        def author_template(self, request, *, domain, provider):
            captured.update(request=request, domain=domain, provider=provider)
            return Result()

    provider = object()

    def create_provider(selection):
        captured["selection"] = selection
        return provider

    monkeypatch.setattr(template_cli, "create_model_provider", create_provider)
    monkeypatch.setattr(template_cli, "TemplateApplication", StubApplication)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "code",
            "--provider",
            "ollama",
            "--model",
            "qwen-test",
            "--prompt",
            "Create a question about graph traversal",
            "--difficulty",
            "advanced",
        ],
    )

    exit_code = template_cli.main()

    assert exit_code == 0
    assert captured["provider"] is provider
    assert isinstance(captured["domain"], CodeDomain)
    assert captured["selection"].provider == "ollama"
    assert captured["selection"].model == "qwen-test"
    request = captured["request"]
    assert request.prompt == "Create a question about graph traversal"
    assert request.difficulty == "advanced"
    assert request.num_distractors == 3
    assert json.loads(capsys.readouterr().out) == {"validated": True}


def test_evaluate_cli_writes_attempts_and_prints_summary(
    monkeypatch, capsys, tmp_path
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "attempts.jsonl"

    class Summary:
        failed = 0

        def model_dump_json(self, *, indent: int) -> str:
            assert indent == 2
            return json.dumps({"attempts": 2, "validated": 2, "failed": 0})

    class Report:
        summary = Summary()

    class Attempt:
        attempt = 1
        topic = "loops"
        status = "validated"
        total_duration_ms = 1250.0

        class Request:
            difficulty = "beginner"

        request = Request()

        def model_dump_json(self):
            return json.dumps({"attempt": self.attempt, "status": "validated"})

    class StubEvaluator:
        def evaluate(self, **kwargs):
            captured.update(kwargs)
            for number in range(1, kwargs["repetitions"] + 1):
                attempt = Attempt()
                attempt.attempt = number
                kwargs["on_attempt"](attempt)
            return Report()

    monkeypatch.setattr(template_cli, "TemplateEvaluator", StubEvaluator)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "evaluate",
            "--domain",
            "code",
            "--provider",
            "ollama",
            "--model",
            "qwen-test",
            "--topic",
            "loops",
            "--difficulty",
            "beginner",
            "--repetitions",
            "2",
            "--output",
            str(output),
        ],
    )

    exit_code = template_cli.main()

    assert exit_code == 0
    assert captured["provider"] == "ollama"
    assert captured["model"] == "qwen-test"
    assert captured["topics"] == ("loops",)
    assert captured["difficulties"] == ("beginner",)
    assert captured["repetitions"] == 2
    assert [json.loads(line) for line in output.read_text().splitlines()] == [
        {"attempt": 1, "status": "validated"},
        {"attempt": 2, "status": "validated"},
    ]
    captured_output = capsys.readouterr()
    assert "[1] loops/beginner: validated (1.2s)" in captured_output.err
    assert "[2] loops/beginner: validated (1.2s)" in captured_output.err
    assert json.loads(captured_output.out) == {
        "attempts": 2,
        "validated": 2,
        "failed": 0,
    }


@pytest.mark.parametrize("status", ["needs_review", "error"])
def test_author_cli_preserves_unsuccessful_result_and_returns_nonzero(
    monkeypatch, capsys, status
):
    class Result:
        def __init__(self):
            self.status = status

        def model_dump(self, *, mode):
            return {
                "status": self.status,
                "artifact": None,
                "attempts": [{"number": 1}],
            }

    class Application:
        def author_template(self, request, *, domain, provider):
            return Result()

    monkeypatch.setattr(template_cli, "TemplateApplication", Application)
    monkeypatch.setattr(
        template_cli, "create_model_provider", lambda selection: object()
    )
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "code",
            "--provider",
            "openai",
            "--prompt",
            "Addition",
            "--difficulty",
            "beginner",
        ],
    )
    assert template_cli.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": status,
        "artifact": None,
        "attempts": [{"number": 1}],
    }


@pytest.mark.parametrize("command", ["author", "validate"])
def test_checking_commands_require_a_provider(command):
    with pytest.raises(SystemExit):
        template_cli.build_parser().parse_args([command, "--domain", "code"])


def test_validate_cli_selects_checks_through_provider_and_mcp(
    example_registry, monkeypatch, tmp_path, capsys
):
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps({"lesson": "fractions", "value": 7}))
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "validate",
            "--domain",
            "example",
            "--provider",
            "example-provider",
            "--model",
            "selector",
            str(source),
        ],
    )
    assert template_cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert example_registry == ["selector"]
    assert result["status"] == "checked"
    assert result["artifact"]["value"] == 7
    assert result["fixed_plan"] == ["positive_value"]
    assert len(result["attempts"]) == 1
    assert json.loads(source.read_text()) == {"lesson": "fractions", "value": 7}


@pytest.mark.parametrize("status", ["needs_review", "error"])
def test_validate_cli_preserves_unsuccessful_evidence(
    monkeypatch, tmp_path, capsys, status
):
    from pathlib import Path

    from edcraft_validator.application.authoring_contracts import AuthoringResult

    source = Path("examples/templates/arithmetic_linear.json")

    class Application:
        def validate_template(self, candidate, *, domain, provider):
            return AuthoringResult(
                status=status,
                provider="stub",
                model="stub",
                request={},
                prompt_version="test",
                proposal=candidate.model_dump(mode="json"),
                fixed_plan=["code_verify_template_structure"],
                tool_catalogue=[],
                reason="failed",
            )

    monkeypatch.setattr(template_cli, "TemplateApplication", Application)
    monkeypatch.setattr(
        template_cli, "create_model_provider", lambda selection: object()
    )
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "validate",
            "--domain",
            "code",
            "--provider",
            "openai",
            str(source),
        ],
    )
    assert template_cli.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == status
