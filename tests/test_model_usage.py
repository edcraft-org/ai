"""Usage survives failures, covers every call, and stays honest when unavailable."""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from test_authoring_loop import Executor, Provider, RecordingClient, run, wrong_answer
from test_openai_compatible_provider import code_response, generation_request

from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.llm_errors import GenerationError, GenerationResponseError
from edcraft_validator.llm.ollama_provider import OllamaProvider
from edcraft_validator.llm.openai_compatible_provider import OpenAICompatibleProvider
from edcraft_validator.llm.usage import ModelCallRecord, TokenUsage, summarize_usage


@pytest.mark.parametrize("provider_name", ["openai", "soclaas"])
def test_openai_compatible_usage_survives_bad_json_and_resets_after_transport_failure(
    provider_name,
):
    responses = [
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=123, completion_tokens=45),
            choices=[SimpleNamespace(message=SimpleNamespace(content="{invalid"))],
        ),
        RuntimeError("connection interrupted"),
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=0),
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="Done", tool_calls=[]))
            ],
        ),
    ]

    def create(**kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider = OpenAICompatibleProvider(provider_name, client, model="test")
    with pytest.raises(GenerationResponseError):
        provider.generate(generation_request())
    assert provider.last_usage == TokenUsage(input_tokens=123, output_tokens=45)
    with pytest.raises(GenerationError):
        provider.generate(generation_request())
    assert provider.last_usage == TokenUsage()
    provider.tool_turn([], [])
    assert provider.last_usage == TokenUsage(input_tokens=20, output_tokens=0)


def test_missing_or_invalid_openai_usage_does_not_break_valid_generation():
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=-1, completion_tokens="12"),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(code_response()))
            )
        ],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response))
    )
    provider = OpenAICompatibleProvider("openai", client, model="test")
    provider.generate(generation_request())
    assert provider.last_usage == TokenUsage()
    del response.usage
    provider.generate(generation_request())
    assert provider.last_usage == TokenUsage()


@pytest.mark.parametrize(
    "body",
    [
        {"message": {"content": "{bad"}, "prompt_eval_count": 50, "eval_count": 10},
        {
            "message": {"content": "partial"},
            "done_reason": "length",
            "prompt_eval_count": 50,
            "eval_count": 10,
        },
    ],
)
def test_ollama_usage_survives_parse_and_output_budget_failures(monkeypatch, body):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps(body).encode()

    monkeypatch.setattr(
        "edcraft_validator.llm.ollama_provider.urlopen",
        lambda *args, **kwargs: Response(),
    )
    provider = OllamaProvider(model="test")
    with pytest.raises(GenerationResponseError):
        provider.generate(generation_request())
    assert provider.last_usage == TokenUsage(input_tokens=50, output_tokens=10)

    def unavailable(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("edcraft_validator.llm.ollama_provider.urlopen", unavailable)
    with pytest.raises(GenerationError):
        provider.tool_turn([], [])
    assert provider.last_usage == TokenUsage()


def test_usage_counts_revisions_checking_and_failed_acknowledgement_per_job():
    class Metered(Provider):
        def generate(self, request):
            self.last_usage = TokenUsage(input_tokens=100, output_tokens=20)
            return super().generate(request)

        def tool_turn(self, messages, tools):
            self.last_usage = TokenUsage(input_tokens=30, output_tokens=5)
            if not tools:
                raise GenerationResponseError("invalid acknowledgement")
            return super().tool_turn(messages, tools)

    result, _ = run(Metered([wrong_answer(), Provider().proposals[0]]))
    assert result.status == "checked"
    assert [call.operation for call in result.model_calls] == [
        "generation",
        "checking",
        "revision",
        "checking",
        "acknowledgement",
    ]
    assert result.model_calls[-1].error == "invalid_response"
    assert result.usage.model_call_count == 5
    assert result.usage.input_tokens == 290
    assert result.usage.output_tokens == 55
    assert result.usage.unavailable_call_count == 0
    provider = Metered()
    first, _ = run(provider)
    second, _ = run(provider)
    assert first.usage.model_call_count == second.usage.model_call_count == 3


def test_initial_generation_failure_retains_usage_settings_and_zero_attempts():
    class Failure(Provider):
        def generate(self, request):
            self.last_usage = TokenUsage(input_tokens=60, output_tokens=15)
            raise GenerationResponseError("invalid initial JSON")

    result, client = run(Failure())
    assert result.status == "error"
    assert result.attempts == []
    assert client.dispatches == []
    assert result.provider_settings == {"mode": "scripted"}
    assert len(result.tool_catalogue) == 3
    assert result.failure.stage == "generation"
    assert result.failure.code == "invalid_response"
    assert result.usage.input_tokens == 60
    assert result.usage.output_tokens == 15
    assert result.duration_ms >= result.generation_duration_ms > 0


def test_providers_without_usage_remain_supported_and_totals_are_not_zero():
    result, _ = run(Provider())
    assert result.status == "checked"
    assert result.usage.model_call_count == result.usage.unavailable_call_count == 3
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert all(call.usage_unavailable_reason for call in result.model_calls)


def test_job_timer_includes_mcp_setup_and_teardown(monkeypatch):
    from edcraft_validator.application import template_workflow

    clock = [0.0]
    monkeypatch.setattr(
        template_workflow, "time", SimpleNamespace(perf_counter=lambda: clock[0])
    )

    class TimedClient(RecordingClient):
        def __enter__(self):
            clock[0] += 2
            return super().__enter__()

        def __exit__(self, *args):
            clock[0] += 3
            return super().__exit__(*args)

    class TimedProvider(Provider):
        def generate(self, request):
            clock[0] += 7
            return super().generate(request)

    result, _ = run(TimedProvider(), TimedClient(Executor()))
    assert result.status == "checked"
    assert result.duration_ms == 12000
    assert result.generation_duration_ms == 7000


def test_partial_usage_keeps_reported_counts_without_claiming_complete_totals():
    summary = summarize_usage(
        [
            ModelCallRecord(
                operation="generation",
                duration_ms=10,
                input_tokens=80,
                output_tokens=10,
            ),
            ModelCallRecord(operation="revision", duration_ms=10, input_tokens=20),
            ModelCallRecord(operation="checking", duration_ms=10),
        ]
    )
    assert summary.model_call_count == 3
    assert summary.unavailable_call_count == 2
    assert summary.input_tokens is None and summary.output_tokens is None
    assert summary.reported_input_tokens == 100
    assert summary.reported_output_tokens == 10


def test_ollama_generation_and_tool_turn_capture_native_usage(monkeypatch):
    class Proposal(BaseModel):
        value: int

    bodies = [
        {
            "message": {"content": '{"value":7}'},
            "prompt_eval_count": 9,
            "eval_count": 4,
        },
        {
            "message": {
                "tool_calls": [{"function": {"name": "check", "arguments": {}}}]
            },
            "prompt_eval_count": 11,
            "eval_count": 3,
        },
    ]

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps(bodies.pop(0)).encode()

    monkeypatch.setattr(
        "edcraft_validator.llm.ollama_provider.urlopen",
        lambda *args, **kwargs: Response(),
    )
    provider = OllamaProvider(model="test")
    assert (
        provider.generate(
            StructuredGenerationRequest(
                messages=[], response_model=Proposal, prompt_version="test"
            )
        ).value
        == 7
    )
    assert provider.last_usage == TokenUsage(input_tokens=9, output_tokens=4)
    assert provider.tool_turn([], []).calls[0].name == "check"
    assert provider.last_usage == TokenUsage(input_tokens=11, output_tokens=3)
