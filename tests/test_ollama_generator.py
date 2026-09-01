import json

from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.ollama import OllamaQuestionGenerator
from edcraft_validator.generation.openai import OpenAIQuestionDraftResponse


def test_ollama_generator_uses_native_schema_endpoint(monkeypatch) -> None:
    # Ollama must use its native endpoint and pass the Pydantic JSON schema.
    captured: dict[str, object] = {}
    response = OpenAIQuestionDraftResponse(
        code="def square(x):\n    return x * x",
        entry_function="square",
        inputs=[],
        question="What does square(4) return?",
        distractors=[
            {"kind": "scalar", "scalar": value, "items": [], "properties": []}
            for value in [4, 8, 20]
        ],
        distractor_reasons=["reason"] * 3,
        question_type="mcq",
    )

    class ResponseWithJson:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"message": {"content": response.model_dump_json()}}
            ).encode()

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
    assert captured["timeout"] == 300
