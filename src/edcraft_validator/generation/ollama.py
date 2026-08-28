import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.generation.openai import (
    _SYSTEM_PROMPT,
    OpenAICompatibleQuestionGenerator,
    OpenAIGenerationError,
    OpenAIQuestionDraftResponse,
    _build_prompt,
)
from edcraft_validator.models import ValidationReport


class OllamaQuestionGenerator(OpenAICompatibleQuestionGenerator):
    """Generate a draft through Ollama's native schema-constrained API."""

    def __init__(
        self, client: object | None = None, *, model: str | None = None
    ) -> None:
        self.provider = "ollama"
        self.client = client
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft:
        parsed = self._request_model(
            _SYSTEM_PROMPT,
            _build_prompt(request, feedback),
            OpenAIQuestionDraftResponse,
        )
        return QuestionDraft(
            code=parsed.code,
            entry_function=parsed.entry_function,
            inputs={item.name: item.value.to_python() for item in parsed.inputs},
            question=parsed.question,
            distractors=[item.to_python() for item in parsed.distractors],
            distractor_reasons=parsed.distractor_reasons,
            question_type=parsed.question_type,
        )

    def _request_model(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            content = self._ollama_request(messages, schema)
            if not content:
                raise ValueError("empty response")
            return schema.model_validate_json(content)
        except (IndexError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
            raise OpenAIGenerationError(
                f"Model returned invalid question JSON: {exc}"
            ) from exc

    def _ollama_request(
        self, messages: list[dict[str, str]], schema: type[BaseModel]
    ) -> str:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0},
        }
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = json.load(response)
            return body["message"]["content"]
        except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
