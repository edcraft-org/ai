import json

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.ollama import OllamaQuestionGenerator
from edcraft_validator.models import ValidationIssue, ValidationReport


def test_ollama_generator_uses_native_schema_endpoint(monkeypatch) -> None:
    # Ollama must use its native endpoint and pass the Pydantic JSON schema.
    captured: dict[str, object] = {}
    response = {
        "code": "def square(x):\n    return x * x",
        "entry_function": "square",
        "inputs": {"x": 4},
        "question": "What does square(4) return?",
        "distractors": [
            {"value": 4, "reason": "reason"},
            {"value": 8, "reason": "reason"},
            {"value": 20, "reason": "reason"},
        ],
        "question_type": "mcq",
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

    monkeypatch.setattr(
        "edcraft_validator.generation.ollama.urlopen",
        fake_urlopen,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    draft = OllamaQuestionGenerator(model="qwen2.5").generate_draft(
        GenerationRequest(topic="arithmetic", difficulty="beginner")
    )

    assert draft.entry_function == "square"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["format"]["type"] == "object"
    assert captured["payload"]["format"]["properties"]["inputs"]["type"] == "object"
    assert captured["payload"]["format"]["properties"]["distractors"]["minItems"] == 3
    assert captured["payload"]["format"]["properties"]["distractors"]["maxItems"] == 3
    distractor_schema = captured["payload"]["format"]["properties"]["distractors"]
    distractor_ref = distractor_schema["items"]["$ref"]
    distractor_definition = captured["payload"]["format"]["$defs"][
        distractor_ref.rsplit("/", 1)[-1]
    ]
    assert distractor_definition["properties"]["value"]
    assert distractor_definition["properties"]["reason"]["minLength"] == 1
    assert "Direct calls may use only" in captured["payload"]["messages"][0]["content"]
    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "claims the distractor" in system_prompt
    assert "correct calculation" in system_prompt
    assert "reason describes how" in captured["payload"]["messages"][0]["content"]
    assert captured["timeout"] == 300


def test_ollama_retry_prompt_includes_computed_answer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class ResponseWithJson:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "code": "def square(x):\n    return x * x",
                                "entry_function": "square",
                                "inputs": {"x": 4},
                                "question": "What does square(4) return?",
                                "distractors": [
                                    {"value": 8, "reason": "adds instead"},
                                    {"value": 12, "reason": "subtracts"},
                                    {"value": 20, "reason": "multiplies twice"},
                                ],
                                "question_type": "mcq",
                            }
                        )
                    }
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return ResponseWithJson()

    monkeypatch.setattr("edcraft_validator.generation.ollama.urlopen", fake_urlopen)
    generator = OllamaQuestionGenerator(model="qwen2.5")
    generator.generate_draft(
        GenerationRequest(topic="arithmetic", difficulty="beginner"),
        feedback=ValidationReport(
            status="invalid",
            actual_answer=16,
            issues=[
                ValidationIssue(
                    code="DISTRACTOR_EQUALS_ANSWER",
                    message="Distractor 0 is also correct",
                )
            ],
        ),
    )

    user_prompt = captured["payload"]["messages"][1]["content"]
    assert "normal return value as 16" in user_prompt
    assert "Do not include that exact value" in user_prompt


def test_ollama_generates_the_shared_template_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    response = {
        "template_id": "arithmetic.linear_sum",
        "version": 1,
        "topic": "arithmetic",
        "difficulty": "beginner",
        "code": "def calculate(a, b):\n    return a + b",
        "entry_function": "calculate",
        "parameters": [
            {"name": "a", "values": [1, 2]},
            {"name": "b", "values": [3, 4]},
        ],
        "question_template": "What does calculate({a}, {b}) return?",
        "answer_target": "return_value",
        "answer_expression": "a + b",
        "distractors": [
            {"expression": "a - b", "reason_template": "Subtracts b."},
            {"expression": "a * b", "reason_template": "Multiplies."},
            {"expression": "a + b + 1", "reason_template": "Adds one."},
        ],
        "question_type": "mcq",
    }

    class ResponseWithJson:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"message": {"content": json.dumps(response)}}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return ResponseWithJson()

    monkeypatch.setattr("edcraft_validator.generation.ollama.urlopen", fake_urlopen)

    result = OllamaQuestionGenerator(model="qwen2.5").generate_template(
        GenerationRequest(topic="arithmetic", difficulty="beginner")
    )

    assert result.template_id == "arithmetic.linear_sum"
    assert captured["payload"]["format"]["properties"]["parameters"]["type"] == "array"
    assert "finite Cartesian product" in captured["payload"]["messages"][0]["content"]
    assert "answer_target=return_value" in captured["payload"]["messages"][1]["content"]
