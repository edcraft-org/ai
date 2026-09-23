import json

import pytest

from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.domains.code.prompt_builder import build_code_generation_request
from edcraft_validator.llm.llm_errors import (
    GenerationError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.llm.ollama_provider import (
    OllamaProvider,
    _num_predict,
    _temperature,
    _timeout_seconds,
)


@pytest.fixture(autouse=True)
def isolated_ollama_settings(monkeypatch):
    """Unit tests control configuration independently of the developer's shell."""
    for variable in (
        "OLLAMA_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_TIMEOUT_SECONDS",
        "OLLAMA_TEMPERATURE",
        "OLLAMA_NUM_PREDICT",
    ):
        monkeypatch.delenv(variable, raising=False)


def generation_request(topic: str = "arithmetic", difficulty: str = "beginner"):
    return build_code_generation_request(
        CodeTemplateRequest(topic=topic, difficulty=difficulty)
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

    monkeypatch.setattr("edcraft_validator.llm.ollama_provider.urlopen", fake_urlopen)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("OLLAMA_TEMPERATURE", raising=False)

    result = OllamaProvider(model="qwen2.5").generate(generation_request())

    assert result.entry_function == "calculate"
    assert result.parameters[0].values == [1, 2]
    assert captured["url"] == "http://localhost:11434/api/chat"
    payload = captured["payload"]
    schema = payload["format"]
    assert schema["properties"]["parameters"]["type"] == "array"
    parameter_schema = schema["$defs"]["CodeParameterResponse"]
    assert parameter_schema["properties"]["values"]["items"] == {"type": "string"}
    assert "topic" not in schema["properties"]
    assert "question_template" not in schema["properties"]
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_predict"] == 2048
    messages = payload["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "answer_target=return_value" in messages[1]["content"]
    assert "exactly 3 distractor candidates" in messages[1]["content"]
    assert "Use strings for every item" in messages[1]["content"]
    assert captured["timeout"] == 300


def test_ollama_reports_common_response_schema_failures(monkeypatch) -> None:
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
        OllamaProvider,
        "_ollama_request",
        lambda self, messages, schema: json.dumps(invalid),
    )

    with pytest.raises(GenerationSchemaError, match="local schema validation"):
        OllamaProvider().generate(generation_request())


def test_ollama_reports_duplicate_parameter_values_as_schema_error(
    monkeypatch,
) -> None:
    duplicate = {
        "code": "def calculate(a):\n    return a",
        "entry_function": "calculate",
        "parameters": [{"name": "a", "kind": "integer", "values": ["2", "2"]}],
        "answer_expression": "a",
        "distractors": [
            {"expression": "a + 1", "reason_template": "Adds one."},
            {"expression": "a - 1", "reason_template": "Subtracts one."},
            {"expression": "a + 2", "reason_template": "Adds two."},
        ],
    }
    monkeypatch.setattr(
        OllamaProvider,
        "_ollama_request",
        lambda self, messages, schema: json.dumps(duplicate),
    )

    with pytest.raises(
        GenerationSchemaError, match="parameter values must be unique"
    ) as error:
        OllamaProvider().generate(generation_request())

    assert error.value.category == "schema_validation"


def test_ollama_reports_timeout_separately(monkeypatch) -> None:
    def timeout(request, timeout):
        raise TimeoutError

    monkeypatch.setattr("edcraft_validator.llm.ollama_provider.urlopen", timeout)

    with pytest.raises(GenerationTimeoutError, match="timed out after 300 seconds"):
        OllamaProvider().generate(generation_request())


def test_ollama_reports_connection_reset_as_transport_failure(monkeypatch) -> None:
    def reset(request, timeout):
        raise ConnectionResetError("peer restarted")

    monkeypatch.setattr("edcraft_validator.llm.ollama_provider.urlopen", reset)

    with pytest.raises(GenerationTransportError, match="connection was interrupted"):
        OllamaProvider().generate(generation_request())


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
