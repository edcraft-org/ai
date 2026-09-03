import json

import pytest

from edcraft_validator.generation.base import (
    GenerationError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.ollama import (
    OllamaTemplateGenerator,
    _num_predict,
    _temperature,
    _timeout_seconds,
    parse_ollama_proposal,
)


def test_ollama_generates_template_with_native_schema_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}
    response = {
        "code": "def calculate(a, b):\n    return a + b",
        "entry_function": "calculate",
        "parameters": [
            {"name": "a", "kind": "integer", "values": ["1", "2"]},
            {"name": "b", "kind": "integer", "values": ["3", "4"]},
        ],
        "answer_expression": "a + b",
        "distractors": [
            {"expression": "a - b", "reason_template": "Subtracts b."},
            {"expression": "a * b", "reason_template": "Multiplies."},
            {"expression": "a + b + 1", "reason_template": "Adds one."},
            {"expression": "a + b - 1", "reason_template": "Subtracts one."},
            {"expression": "a + b + 2", "reason_template": "Adds two."},
        ],
    }

    class ResponseWithJson:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"message": {"content": json.dumps(response)}}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return ResponseWithJson()

    monkeypatch.setattr("edcraft_validator.generation.ollama.urlopen", fake_urlopen)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("OLLAMA_TEMPERATURE", raising=False)

    result = OllamaTemplateGenerator(model="qwen2.5").generate_proposal(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
    )

    assert result.entry_function == "calculate"
    assert result.parameters[0].values == [1, 2]
    assert captured["url"] == "http://localhost:11434/api/chat"
    payload = captured["payload"]
    schema = payload["format"]
    assert schema["properties"]["parameters"]["type"] == "array"
    parameter_schema = schema["$defs"]["OllamaParameterWire"]
    assert parameter_schema["properties"]["values"]["items"] == {"type": "string"}
    assert "topic" not in schema["properties"]
    assert "question_template" not in schema["properties"]
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_predict"] == 2048
    messages = payload["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "answer_target=return_value" in messages[1]["content"]
    assert "exactly 3 distractor candidates" in messages[1]["content"]
    assert captured["timeout"] == 300


def test_ollama_wire_converts_each_supported_parameter_kind() -> None:
    content = json.dumps(
        {
            "code": "def inspect(count, enabled, label):\n    return count",
            "entry_function": "inspect",
            "parameters": [
                {"name": "count", "kind": "integer", "values": ["-2", "3"]},
                {
                    "name": "enabled",
                    "kind": "boolean",
                    "values": ["true", "false"],
                },
                {"name": "label", "kind": "string", "values": ["a", "b"]},
            ],
            "answer_expression": "count",
            "distractors": [
                {"expression": "count + 1", "reason_template": "Adds one."},
                {"expression": "count - 1", "reason_template": "Subtracts one."},
                {"expression": "count + 2", "reason_template": "Adds two."},
            ],
        }
    )

    proposal = parse_ollama_proposal(content)

    assert proposal.parameters[0].values == [-2, 3]
    assert proposal.parameters[1].values == [True, False]
    assert proposal.parameters[2].values == ["a", "b"]


def test_ollama_wire_converts_integer_lists() -> None:
    content = json.dumps(
        {
            "code": "def total(values):\n    return sum(values)",
            "entry_function": "total",
            "parameters": [
                {
                    "name": "values",
                    "kind": "integer_list",
                    "values": ["[1,2]", "[-3,4]"],
                }
            ],
            "answer_expression": "sum(values)",
            "distractors": [
                {"expression": "len(values)", "reason_template": "Counts items."},
                {"expression": "sum(values) + 1", "reason_template": "Adds one."},
                {"expression": "sum(values) - 1", "reason_template": "Subtracts one."},
            ],
        }
    )

    proposal = parse_ollama_proposal(content)

    assert proposal.parameters[0].values == [[1, 2], [-3, 4]]


def test_ollama_reports_local_wire_schema_failures(monkeypatch) -> None:
    invalid = {
        "code": "def calculate(a):\n    return a",
        "entry_function": "calculate",
        "parameters": [{"name": "a", "kind": "integer", "values": ["not-an-int", "2"]}],
        "answer_expression": "a",
        "distractors": [
            {"expression": "a + 1", "reason_template": "Adds one."},
            {"expression": "a - 1", "reason_template": "Subtracts one."},
            {"expression": "a + 2", "reason_template": "Adds two."},
        ],
    }
    monkeypatch.setattr(
        OllamaTemplateGenerator,
        "_ollama_request",
        lambda self, messages, schema: json.dumps(invalid),
    )

    with pytest.raises(GenerationSchemaError, match="local schema validation"):
        OllamaTemplateGenerator().generate_proposal(
            TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
        )


def test_ollama_reports_timeout_separately(monkeypatch) -> None:
    def timeout(request, timeout):
        raise TimeoutError

    monkeypatch.setattr("edcraft_validator.generation.ollama.urlopen", timeout)

    with pytest.raises(GenerationTimeoutError, match="timed out after 300 seconds"):
        OllamaTemplateGenerator().generate_proposal(
            TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
        )


def test_ollama_reports_connection_reset_as_transport_failure(monkeypatch) -> None:
    def reset(request, timeout):
        raise ConnectionResetError("peer restarted")

    monkeypatch.setattr("edcraft_validator.generation.ollama.urlopen", reset)

    with pytest.raises(GenerationTransportError, match="connection was interrupted"):
        OllamaTemplateGenerator().generate_proposal(
            TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
        )


@pytest.mark.parametrize(
    ("variable", "value", "reader", "message"),
    [
        ("OLLAMA_TIMEOUT_SECONDS", "0", _timeout_seconds, "greater than zero"),
        ("OLLAMA_TIMEOUT_SECONDS", "slow", _timeout_seconds, "must be a number"),
        ("OLLAMA_TEMPERATURE", "3", _temperature, "between 0 and 2"),
        ("OLLAMA_TEMPERATURE", "warm", _temperature, "must be a number"),
        ("OLLAMA_NUM_PREDICT", "127", _num_predict, "between 128 and 4096"),
        ("OLLAMA_NUM_PREDICT", "many", _num_predict, "must be an integer"),
    ],
)
def test_ollama_rejects_invalid_generation_bounds(
    monkeypatch, variable, value, reader, message
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(GenerationError, match=message):
        reader()


def test_ollama_prompt_metadata_is_stable_and_wire_specific() -> None:
    generator = OllamaTemplateGenerator(model="qwen-test")
    request = TemplateAuthoringRequest(topic="loops", difficulty="advanced")

    first = generator.prompt_metadata(request)
    second = generator.prompt_metadata(request)

    assert first == second
    assert first.version == "code-template-v8+ollama-wire-v1"
    assert len(first.sha256) == 64
    assert (
        first.sha256
        != generator.prompt_metadata(
            TemplateAuthoringRequest(topic="loops", difficulty="beginner")
        ).sha256
    )
