import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.prompt_builder import build_code_generation_request
from edcraft_validator.llm.llm_contracts import (
    StructuredGenerationRequest,
    ToolCatalogueSnapshot,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationSchemaError,
)
from edcraft_validator.llm.openai_compatible_provider import (
    OpenAICompatibleProvider,
    OpenAIGenerationError,
    _api_key,
    _base_url,
    _max_retries,
    _model,
    _timeout_seconds,
)
from edcraft_validator.llm.tool_context import constrained_check_plan


def generation_request(
    prompt: str = "Create an arithmetic question", difficulty: str = "easy"
):
    return replace(
        build_code_generation_request(
            CodeTemplateRequest(prompt=prompt, difficulty=difficulty)
        ),
        offered_tool_names=("code_execution", "code_structure"),
    )


def code_response() -> dict[str, object]:
    return {
        "proposal": {
            "question_template": "What does calculate({a}, {b}) return?",
            "code": "def calculate(a, b):\n    return a + b",
            "entry_function": "calculate",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [3, 4]},
            ],
            "answer_target": "return_value",
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a - b", "reason_template": "Subtracts b."},
                {"expression": "a * b", "reason_template": "Multiplies."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
            ],
        },
        "checks": [
            {"name": "code_execution", "arguments": {}},
        ],
    }


class RecordingCompletions:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.arguments: dict[str, object] = {}

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.arguments = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content, tool_calls=None)
                )
            ]
        )


def client_with(response: dict[str, object] | None) -> SimpleNamespace:
    content = json.dumps(response) if response is not None else None
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


def client_with_content(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions(content))
    )


@pytest.mark.parametrize("injected", [False, True])
def test_close_only_closes_owned_sdk_clients(monkeypatch, injected):
    closed = []
    client = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "edcraft_validator.llm.openai_compatible_provider.OpenAI",
        lambda **kwargs: client,
    )
    provider = OpenAICompatibleProvider("openai", client if injected else None)
    provider.close()
    assert closed == ([] if injected else [True])


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_catalogue_names_are_wire_schema_choices_and_checked_locally(provider_name):
    response = code_response()
    client = client_with(response)
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    request = replace(
        generation_request(), offered_tool_names=("code_execution", "code_structure")
    )
    result = provider.generate(request)
    assert type(result) is request.response_model
    schema = client.chat.completions.arguments["response_format"]["json_schema"][
        "schema"
    ]
    assert (
        schema["$defs"]["CatalogueCheck_code_execution"]["properties"]["name"]["const"]
        == "code_execution"
    )
    assert (
        schema["$defs"]["CatalogueCheck_code_structure"]["properties"]["name"]["const"]
        == "code_structure"
    )
    assert "CatalogueCheck" not in request.response_model.model_json_schema()["$defs"]
    response["checks"][0]["name"] = "invented_tool"
    client.chat.completions.content = json.dumps(response)
    with pytest.raises(GenerationSchemaError):
        provider.generate(request)


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_generates_template_using_strict_structured_outputs(
    monkeypatch, provider_name
) -> None:
    monkeypatch.delenv(f"{provider_name.upper()}_RESPONSE_FORMAT", raising=False)
    monkeypatch.delenv(f"{provider_name.upper()}_GENERATION_MAX_TOKENS", raising=False)
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test-model")

    result = provider.generate(generation_request())

    assert result.proposal.entry_function == "calculate"
    assert result.proposal.parameters[0].values == [1, 2]
    assert result.checks[0].name == "code_execution"
    assert client.chat.completions.arguments["model"] == "test-model"
    assert client.chat.completions.arguments.get("max_tokens") == (
        32768 if provider_name == "soclaas" else None
    )
    response_format = client.chat.completions.arguments["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == (
        "template_proposal_and_check_plan"
    )
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]) == {"proposal", "checks"}
    proposal_schema = schema["$defs"]["CodeProposalResponse"]
    assert "question_template" in proposal_schema["properties"]
    assert "answer_target" in proposal_schema["properties"]
    parameter_items = proposal_schema["properties"]["parameters"]["items"]
    assert len(parameter_items["anyOf"]) == 4
    integer_schema = schema["$defs"]["IntegerParameterResponse"]
    assert integer_schema["properties"]["values"]["items"] == {"type": "integer"}
    check_schema = schema["$defs"]["CatalogueCheck_code_execution"]
    assert set(check_schema["required"]) == set(check_schema["properties"])
    arguments_schema = schema["$defs"]["RecommendedCheckArguments"]
    assert arguments_schema["additionalProperties"] is False
    assert arguments_schema["properties"] == {}
    messages = client.chat.completions.arguments["messages"]
    assert "property-based" in messages[0]["content"]
    assert "Create an arithmetic question" in messages[1]["content"]
    assert "at least 3 distractor candidates" in messages[1]["content"]
    assert "Use native JSON values" in messages[1]["content"]
    settings = provider.generation_settings()
    assert settings["response_format"] == response_format["type"]
    assert settings["strict"] == response_format["json_schema"]["strict"]
    assert settings["sampling"] == "provider_defaults"
    assert "temperature" not in client.chat.completions.arguments
    assert "tools" not in client.chat.completions.arguments
    assert "tool_choice" not in client.chat.completions.arguments
    assert "parallel_tool_calls" not in client.chat.completions.arguments
    assert "api_key" not in settings


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_openai_receives_check_purposes_without_internal_mcp_schemas(
    provider_name,
) -> None:
    tool = {
        "name": "code_verify_template_structure",
        "description": "Check structure",
        "inputSchema": {"type": "object", "properties": {"candidate": {}}},
        "outputSchema": {"type": "object", "properties": {"status": {}}},
        "_meta": {"fastmcp": {"version": "1.0"}},
    }
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test-model")

    provider.generate(
        replace(
            generation_request(),
            tool_catalogue=ToolCatalogueSnapshot.from_definitions((tool,)),
        )
    )

    messages = client.chat.completions.arguments["messages"]
    context = json.loads(messages[1]["content"].split("\n", 1)[1])
    assert context[0]["name"] == tool["name"]
    assert context[0]["description"] == tool["description"]
    assert context[0]["arguments_schema"]["properties"] == {}
    assert "inputSchema" not in context[0] and "outputSchema" not in context[0]
    assert messages[1]["role"] == "system"


def test_provider_accepts_a_schema_from_another_domain() -> None:
    class ExampleProposal(BaseModel):
        equation: str

    client = client_with_content('{"equation":"x + 1"}')
    provider = OpenAICompatibleProvider("openai", client, model="test-model")
    request = StructuredGenerationRequest(
        messages=[{"role": "user", "content": "Create an equation"}],
        response_model=ExampleProposal,
        prompt_version="example-v1",
    )

    result = provider.generate(request)

    assert result == ExampleProposal(equation="x + 1")
    schema = client.chat.completions.arguments["response_format"]["json_schema"]
    assert "equation" in schema["schema"]["properties"]


def test_reports_empty_template_response() -> None:
    provider = OpenAICompatibleProvider("openai", client_with(None), model="test-model")

    with pytest.raises(
        OpenAIGenerationError, match="returned an empty response"
    ) as error:
        provider.generate(generation_request())

    assert error.value.category == "invalid_response"


def test_reports_duplicate_parameter_values_as_schema_error() -> None:
    payload = code_response()
    payload["proposal"]["parameters"][0]["values"] = [2, 2]
    provider = OpenAICompatibleProvider(
        "openai", client_with_content(json.dumps(payload)), model="test-model"
    )

    with pytest.raises(
        GenerationSchemaError, match="parameter values must be unique"
    ) as error:
        provider.generate(generation_request())

    assert error.value.category == "schema_validation"


def test_reports_parameter_type_mismatch_as_schema_error() -> None:
    payload = code_response()
    payload["proposal"]["parameters"][0]["values"] = ["not-an-int", "2"]
    provider = OpenAICompatibleProvider(
        "openai", client_with_content(json.dumps(payload)), model="test-model"
    )

    with pytest.raises(GenerationSchemaError, match="local schema validation") as error:
        provider.generate(generation_request())

    assert error.value.category == "schema_validation"


def test_reports_malformed_json_as_response_error() -> None:
    class ExampleProposal(BaseModel):
        equation: str

    provider = OpenAICompatibleProvider(
        "openai", client_with_content('{"equation":'), model="test-model"
    )

    with pytest.raises(GenerationResponseError, match="malformed JSON") as error:
        provider.generate(
            StructuredGenerationRequest(
                messages=[{"role": "user", "content": "Create an equation"}],
                response_model=ExampleProposal,
                prompt_version="example-v1",
            )
        )

    assert error.value.category == "invalid_response"


def test_provider_uses_provider_specific_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("SOCLAAS_API_KEY", "soclaas-key")
    monkeypatch.setenv("SOCLAAS_BASE_URL", "https://soclaas.example/v1")

    assert _api_key("openai") == "openai-key"
    assert _base_url("openai") == "https://openai.example/v1"
    assert _api_key("soclaas") == "soclaas-key"
    assert _base_url("soclaas") == "https://soclaas.example/v1"


def test_provider_configuration_strips_surrounding_whitespace(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "  openai-key\n")
    monkeypatch.setenv("OPENAI_BASE_URL", " https://openai.example/v1/ \n")

    assert _api_key("openai") == "openai-key"
    assert _base_url("openai") == "https://openai.example/v1/"


def test_provider_configuration_rejects_internal_whitespace(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key\nsecond-line")

    with pytest.raises(OpenAIGenerationError, match="invalid whitespace"):
        _api_key("openai")


def test_soclaas_defaults_to_glm_and_preserves_explicit_overrides(monkeypatch) -> None:
    monkeypatch.delenv("SOCLAAS_MODEL", raising=False)
    assert _model("soclaas") == "x-test-1"
    monkeypatch.setenv("SOCLAAS_MODEL", "  ")
    assert _model("soclaas") == "x-test-1"
    monkeypatch.setenv("SOCLAAS_MODEL", " qwen3.6:35b ")
    assert _model("soclaas") == "qwen3.6:35b"
    assert (
        OpenAICompatibleProvider(
            "soclaas", client=object(), model="explicit-model"
        ).model
        == "explicit-model"
    )


def test_openai_client_uses_configured_endpoint_and_bounds(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "edcraft_validator.llm.openai_compatible_provider.OpenAI", RecordingOpenAI
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "bring-your-own-model")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")

    provider = OpenAICompatibleProvider("openai")

    assert provider.model == "bring-your-own-model"
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://openai.example/v1"
    assert captured["timeout"] == 45
    assert captured["max_retries"] == 0


@pytest.mark.parametrize(
    ("variable", "value", "reader", "message"),
    [
        ("OPENAI_TIMEOUT_SECONDS", "0", _timeout_seconds, "greater than zero"),
        ("OPENAI_TIMEOUT_SECONDS", "slow", _timeout_seconds, "must be a number"),
        ("OPENAI_MAX_RETRIES", "-1", _max_retries, "between 0 and 5"),
        ("OPENAI_MAX_RETRIES", "many", _max_retries, "must be an integer"),
    ],
)
def test_openai_rejects_invalid_request_bounds(
    monkeypatch, variable, value, reader, message
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(OpenAIGenerationError, match=message):
        reader("openai")


def test_generation_timeout_is_normalized():
    import httpx
    from openai import APITimeoutError

    from edcraft_validator.llm.llm_errors import GenerationTimeoutError

    def create(**kwargs):
        raise APITimeoutError(request=httpx.Request("POST", "https://api.example/chat"))

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    with pytest.raises(GenerationTimeoutError):
        OpenAICompatibleProvider("openai", client, model="test").generate(
            generation_request()
        )


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
@pytest.mark.parametrize("configured_reasoning", [None, " low ", "", "default"])
def test_reasoning_setting_applies_to_generation(
    monkeypatch, provider_name, configured_reasoning
):
    effort = f"{provider_name.upper()}_REASONING_EFFORT"
    if configured_reasoning is None:
        monkeypatch.delenv(effort, raising=False)
    else:
        monkeypatch.setenv(effort, configured_reasoning)
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    provider.generate(generation_request())
    arguments = client.chat.completions.arguments
    settings = provider.generation_settings()
    reasoning = (configured_reasoning or "").strip() or "default"
    if reasoning == "default":
        assert "reasoning_effort" not in arguments
        if provider_name == "soclaas":
            assert settings["reasoning_effort"] == "provider_default"
        else:
            assert "reasoning_effort" not in settings
    else:
        assert arguments["reasoning_effort"] == reasoning
        assert settings["reasoning_effort"] == reasoning


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
@pytest.mark.parametrize("revision", [False, True])
def test_json_mode_shows_current_schema_and_preserves_code(
    monkeypatch, provider_name, revision
):
    from edcraft_validator.domains.code.proposal_response import CodeProposalResponse

    monkeypatch.setenv(f"{provider_name.upper()}_RESPONSE_FORMAT", "json_object")
    request = generation_request()
    payload = code_response()
    if revision:
        request = replace(
            request,
            response_model=CodeProposalResponse,
            schema_name="template_revision",
        )
        payload = payload["proposal"]
    original_messages = json.dumps(request.messages)
    client = client_with(payload)
    provider = OpenAICompatibleProvider(provider_name, client, model="test")

    result = provider.generate(request)

    proposal = result if revision else result.proposal
    assert proposal.code == code_response()["proposal"]["code"]
    arguments = client.chat.completions.arguments
    assert arguments["response_format"] == {"type": "json_object"}
    instruction = arguments["messages"][-1]["content"]
    assert "line breaks and indentation" in instruction
    supplied_schema = json.loads(instruction.split("\n", 1)[1])
    expected_model = constrained_check_plan(
        request.response_model,
        request.offered_tool_names,
        request.check_argument_models,
    )
    assert supplied_schema == expected_model.model_json_schema()
    assert ("checks" in supplied_schema["properties"]) is not revision
    assert provider.generation_settings()["strict"] is False
    assert json.dumps(request.messages) == original_messages


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_json_mode_still_enforces_local_schema(monkeypatch, provider_name):
    monkeypatch.setenv(f"{provider_name.upper()}_RESPONSE_FORMAT", "json_object")
    provider = OpenAICompatibleProvider(provider_name, client_with({}), model="test")
    with pytest.raises(GenerationSchemaError):
        provider.generate(generation_request())


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_generation_budget_can_be_configured(monkeypatch, provider_name):
    monkeypatch.setenv(f"{provider_name.upper()}_GENERATION_MAX_TOKENS", "32768")
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    provider.generate(generation_request())
    assert client.chat.completions.arguments["max_tokens"] == 32768
    assert provider.generation_settings()["generation_max_tokens"] == 32768


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_provider_rejects_invalid_generation_budget(monkeypatch, provider_name, value):
    variable = f"{provider_name.upper()}_GENERATION_MAX_TOKENS"
    monkeypatch.setenv(variable, value)
    with pytest.raises(OpenAIGenerationError, match=variable):
        OpenAICompatibleProvider(provider_name, object(), model="test")


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_provider_rejects_unknown_output_format(monkeypatch, provider_name):
    variable = f"{provider_name.upper()}_RESPONSE_FORMAT"
    monkeypatch.setenv(variable, "text")
    with pytest.raises(OpenAIGenerationError, match=variable):
        OpenAICompatibleProvider(provider_name, object(), model="test")


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_per_call_reasoning_effort_overrides_configured_default(
    monkeypatch, provider_name
):
    monkeypatch.setenv(f"{provider_name.upper()}_REASONING_EFFORT", "low")
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test")

    provider.generate(replace(generation_request(), reasoning_effort="high"))

    assert client.chat.completions.arguments["reasoning_effort"] == "high"
    assert provider.generation_settings()["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    ("provider_name", "seconds"), [("openai", 120), ("soclaas", 600)]
)
def test_provider_default_timeout_and_retries(monkeypatch, provider_name, seconds):
    monkeypatch.delenv(f"{provider_name.upper()}_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv(f"{provider_name.upper()}_MAX_RETRIES", raising=False)
    assert _timeout_seconds(provider_name) == seconds
    assert _max_retries(provider_name) == 1


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_truncated_generation_retains_usage_before_json_parsing(provider_name):
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8),
        choices=[
            SimpleNamespace(
                finish_reason="length", message=SimpleNamespace(content='{"proposal":')
            )
        ],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    with pytest.raises(GenerationResponseError, match="generation exhausted"):
        provider.generate(generation_request())
    assert provider.last_usage.input_tokens == 20
    assert provider.last_usage.output_tokens == 8


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_provider_validates_feature_arguments_in_initial_structured_plan(provider_name):
    response = code_response()
    response["checks"] = [
        {"name": "code_require_features", "arguments": {"required": ["loop"]}}
    ]
    client = client_with(response)
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    request = replace(
        generation_request(), offered_tool_names=("code_require_features",)
    )
    result = provider.generate(request)
    assert result.checks[0].arguments == {"required": ["loop"]}
    schema = client.chat.completions.arguments["response_format"]["json_schema"][
        "schema"
    ]
    assert (
        schema["$defs"]["RequiredFeaturesArguments"]["properties"]["required"][
            "minItems"
        ]
        == 1
    )
    response["checks"][0]["arguments"] = {"required": []}
    client.chat.completions.content = json.dumps(response)
    with pytest.raises(GenerationSchemaError):
        provider.generate(request)
