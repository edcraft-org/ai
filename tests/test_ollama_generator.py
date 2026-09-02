import json

from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.ollama import OllamaTemplateGenerator


def test_ollama_generates_template_with_native_schema_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}
    response = {
        "code": "def calculate(a, b):\n    return a + b",
        "entry_function": "calculate",
        "parameters": [
            {"name": "a", "kind": "integer", "values": [1, 2]},
            {"name": "b", "kind": "integer", "values": [3, 4]},
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

    result = OllamaTemplateGenerator(model="qwen2.5").generate_proposal(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
    )

    assert result.entry_function == "calculate"
    assert captured["url"] == "http://localhost:11434/api/chat"
    schema = captured["payload"]["format"]
    assert schema["properties"]["parameters"]["type"] == "array"
    assert "topic" not in schema["properties"]
    assert "question_template" not in schema["properties"]
    messages = captured["payload"]["messages"]
    assert "finite Cartesian product" in messages[0]["content"]
    assert "answer_target=return_value" in messages[1]["content"]
    assert "exactly 5 distractor candidates" in messages[1]["content"]
    assert captured["timeout"] == 300
