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


def generation_request(
    prompt: str = "Create an arithmetic question", difficulty: str = "easy"
):
    return build_code_generation_request(
        CodeTemplateRequest(prompt=prompt, difficulty=difficulty)
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


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_generates_template_using_strict_structured_outputs(
    monkeypatch, provider_name
) -> None:
    monkeypatch.setenv("SOCLAAS_RESPONSE_FORMAT", "json_schema")
    client = client_with(code_response())
    provider = OpenAICompatibleProvider(provider_name, client, model="test-model")

    result = provider.generate(generation_request())

    assert result.proposal.entry_function == "calculate"
    assert result.proposal.parameters[0].values == [1, 2]
    assert result.checks[0].name == "code_execution"
    assert client.chat.completions.arguments["model"] == "test-model"
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
    check_schema = schema["$defs"]["RecommendedCheck"]
    assert set(check_schema["required"]) == set(check_schema["properties"])
    arguments_schema = schema["$defs"]["RecommendedCheckArguments"]
    assert arguments_schema["additionalProperties"] is False
    assert arguments_schema["properties"] == {}
    messages = client.chat.completions.arguments["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "Create an arithmetic question" in messages[1]["content"]
    assert "at least 3 distractor candidates" in messages[1]["content"]
    assert "Use native JSON values" in messages[1]["content"]
    settings = provider.generation_settings()
    assert settings["response_format"] == response_format["type"]
    assert settings["strict"] == response_format["json_schema"]["strict"]
    assert settings["sampling"] == "provider_defaults"
    assert "temperature" not in client.chat.completions.arguments
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
    assert json.loads(messages[1]["content"].split("\n", 1)[1]) == [
        {"name": tool["name"], "description": tool["description"]}
    ]
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


def test_soclaas_requires_its_own_model(monkeypatch) -> None:
    monkeypatch.delenv("SOCLAAS_MODEL", raising=False)

    with pytest.raises(OpenAIGenerationError, match="SOCLAAS_MODEL is not configured"):
        _model("soclaas")


def test_openai_client_uses_bounded_timeout_and_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "edcraft_validator.llm.openai_compatible_provider.OpenAI", RecordingOpenAI
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")

    provider = OpenAICompatibleProvider("openai")

    assert provider.model
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


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_native_calls_and_correlated_results_are_preserved(provider_name):
    from edcraft_validator.llm.llm_contracts import ModelTurn, ToolCall

    captured = []

    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="check", arguments='{"required":["loop"]}'
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider = OpenAICompatibleProvider(provider_name, client, model="tool-model")
    tools = [
        {
            "type": "function",
            "function": {"name": "check", "parameters": {"type": "object"}},
        }
    ]
    turn = provider.tool_turn([{"role": "user", "content": "Check it"}], tools)
    assert turn == ModelTurn(
        calls=[
            ToolCall(id="call-1", name="check", arguments_json='{"required":["loop"]}')
        ]
    )
    messages = [
        turn.message(),
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "check",
            "content": '{"status":"failed"}',
        },
    ]
    provider.tool_turn(messages, [])
    assert captured[0]["tools"] == tools
    assert captured[0]["tool_choice"] == "required"
    assert captured[0]["parallel_tool_calls"] is True
    settings = provider.generation_settings()
    assert settings["tool_choice"] == "required"
    assert settings["parallel_tool_calls"] == captured[0]["parallel_tool_calls"]
    assert captured[1]["messages"][0]["tool_calls"][0]["id"] == "call-1"
    assert captured[1]["messages"][1]["tool_call_id"] == "call-1"
    assert "name" not in captured[1]["messages"][1]
    assert messages[1]["name"] == "check"  # Adapter does not mutate the transcript.
    assert "tools" not in captured[1]


def test_native_tool_timeout_is_normalized():
    import httpx
    from openai import APITimeoutError

    from edcraft_validator.llm.llm_errors import GenerationTimeoutError

    def create(**kwargs):
        raise APITimeoutError(request=httpx.Request("POST", "https://api.example/chat"))

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    with pytest.raises(GenerationTimeoutError):
        OpenAICompatibleProvider("openai", client, model="test").tool_turn([], [])


def test_strict_tool_arguments_preserve_mcp_required_fields():
    from edcraft_validator.llm.openai_compatible_provider import _strict_tools

    tool = {
        "type": "function",
        "function": {
            "name": "features",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "required": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["required"],
            },
        },
    }
    strict = _strict_tools([tool])[0]
    assert strict["function"]["strict"] is True
    assert strict["function"]["parameters"]["required"] == ["required"]
    assert "strict" not in tool["function"]
    tool["function"]["parameters"]["required"] = []
    assert "strict" not in _strict_tools([tool])[0]["function"]


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
@pytest.mark.parametrize("configured_limit", [None, "64"])
@pytest.mark.parametrize("configured_reasoning", [None, " low ", "", "default"])
def test_soclaas_request_options_apply_to_the_correct_calls(
    monkeypatch, provider_name, configured_limit, configured_reasoning
):
    if configured_limit is None:
        monkeypatch.delenv("SOCLAAS_TOOL_MAX_TOKENS", raising=False)
    else:
        monkeypatch.setenv("SOCLAAS_TOOL_MAX_TOKENS", configured_limit)
    if configured_reasoning is None:
        monkeypatch.delenv("SOCLAAS_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("SOCLAAS_REASONING_EFFORT", configured_reasoning)
    captured = []

    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps(code_response()), tool_calls=[]
                    ),
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    provider.generate(generation_request())
    provider.tool_turn(
        [],
        [
            {
                "type": "function",
                "function": {"name": "check", "parameters": {"type": "object"}},
            }
        ],
    )
    provider.tool_turn([], [])
    if provider_name == "soclaas":
        assert captured[0]["max_tokens"] == 16384
        assert provider.generation_settings()["generation_max_tokens"] == 16384
        expected = int(configured_limit) if configured_limit else 4096
        assert captured[1]["max_tokens"] == captured[2]["max_tokens"] == expected
        assert provider.generation_settings()["tool_max_tokens"] == expected
        reasoning = (configured_reasoning or "").strip() or "default"
        if reasoning == "default":
            assert all("reasoning_effort" not in request for request in captured)
            assert (
                provider.generation_settings()["reasoning_effort"] == "provider_default"
            )
        else:
            assert all(request["reasoning_effort"] == reasoning for request in captured)
            assert provider.generation_settings()["reasoning_effort"] == reasoning
    else:
        assert all("max_tokens" not in request for request in captured)
        assert "tool_max_tokens" not in provider.generation_settings()
        assert all("reasoning_effort" not in request for request in captured)
        assert "reasoning_effort" not in provider.generation_settings()


@pytest.mark.parametrize("limit", ["0", "-1", "many"])
def test_soclaas_rejects_invalid_tool_output_budget(monkeypatch, limit):
    monkeypatch.setenv("SOCLAAS_TOOL_MAX_TOKENS", limit)
    with pytest.raises(OpenAIGenerationError, match="SOCLAAS_TOOL_MAX_TOKENS"):
        OpenAICompatibleProvider("soclaas", object(), model="test")


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_truncated_tool_response_retains_usage_and_cannot_be_dispatched(provider_name):
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8),
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(name="check", arguments="{}"),
                        )
                    ],
                ),
            )
        ],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    with pytest.raises(GenerationResponseError, match="exhausted its output budget"):
        provider.tool_turn([], [])
    assert provider.last_usage.input_tokens == 20
    assert provider.last_usage.output_tokens == 8


@pytest.mark.parametrize("revision", [False, True])
def test_soclaas_json_mode_shows_current_schema_and_preserves_code(
    monkeypatch, revision
):
    from edcraft_validator.domains.code.proposal_response import CodeProposalResponse

    monkeypatch.delenv("SOCLAAS_RESPONSE_FORMAT", raising=False)
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
    provider = OpenAICompatibleProvider("soclaas", client, model="test")

    result = provider.generate(request)

    proposal = result if revision else result.proposal
    assert proposal.code == code_response()["proposal"]["code"]
    arguments = client.chat.completions.arguments
    assert arguments["response_format"] == {"type": "json_object"}
    instruction = arguments["messages"][-1]["content"]
    assert "line breaks and indentation" in instruction
    supplied_schema = json.loads(instruction.split("\n", 1)[1])
    assert supplied_schema == request.response_model.model_json_schema()
    assert ("checks" in supplied_schema["properties"]) is not revision
    assert provider.generation_settings()["strict"] is False
    assert json.dumps(request.messages) == original_messages


def test_soclaas_json_mode_still_enforces_local_schema(monkeypatch):
    monkeypatch.setenv("SOCLAAS_RESPONSE_FORMAT", "json_object")
    provider = OpenAICompatibleProvider("soclaas", client_with({}), model="test")
    with pytest.raises(GenerationSchemaError):
        provider.generate(generation_request())


def test_soclaas_generation_budget_can_be_configured(monkeypatch):
    monkeypatch.setenv("SOCLAAS_GENERATION_MAX_TOKENS", "32768")
    client = client_with(code_response())
    provider = OpenAICompatibleProvider("soclaas", client, model="test")
    provider.generate(generation_request())
    assert client.chat.completions.arguments["max_tokens"] == 32768
    assert provider.generation_settings()["generation_max_tokens"] == 32768


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_soclaas_rejects_invalid_generation_budget(monkeypatch, value):
    monkeypatch.setenv("SOCLAAS_GENERATION_MAX_TOKENS", value)
    with pytest.raises(OpenAIGenerationError, match="SOCLAAS_GENERATION_MAX_TOKENS"):
        OpenAICompatibleProvider("soclaas", object(), model="test")


def test_soclaas_rejects_unknown_output_format(monkeypatch):
    monkeypatch.setenv("SOCLAAS_RESPONSE_FORMAT", "text")
    with pytest.raises(OpenAIGenerationError, match="SOCLAAS_RESPONSE_FORMAT"):
        OpenAICompatibleProvider("soclaas", object(), model="test")


def test_soclaas_default_timeout_allows_reasoning(monkeypatch):
    monkeypatch.delenv("SOCLAAS_TIMEOUT_SECONDS", raising=False)
    assert _timeout_seconds("soclaas") == 300


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_providers_offer_all_pending_tools_without_mutating_schemas(provider_name):
    client = client_with_content("")
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }
        for name in ("structure", "semantic")
    ]
    original = json.dumps(tools)
    provider.tool_turn([], tools)
    arguments = client.chat.completions.arguments
    assert arguments["tool_choice"] == "required"
    assert arguments["parallel_tool_calls"] is True
    assert len(arguments["tools"]) == 2
    assert arguments["tools"][0]["function"]["strict"] is True
    provider.tool_turn([], tools[1:])
    assert client.chat.completions.arguments["tool_choice"] == "required"
    provider.tool_turn([], [])
    assert "tool_choice" not in client.chat.completions.arguments
    assert json.dumps(tools) == original


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
