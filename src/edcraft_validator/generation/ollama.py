import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.generation.openai import (
    OpenAICompatibleQuestionGenerator,
    OpenAIGenerationError,
)
from edcraft_validator.generation.provider import (
    QuestionDraftResponse,
    build_prompt,
    normalize_plain_response,
)
from edcraft_validator.models import ValidationReport


class OllamaQuestionGenerator(OpenAICompatibleQuestionGenerator):
    """Generate drafts through Ollama while honoring the shared provider contract."""

    def __init__(
        self, client: object | None = None, *, model: str | None = None
    ) -> None:
        self.provider = "ollama"
        self.client = client
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"

    def generate_draft(
        self, request: GenerationRequest, *, feedback: ValidationReport | None = None
    ) -> QuestionDraft:
        parsed = self._request_model(
            _OLLAMA_SYSTEM_PROMPT,
            build_prompt(request, feedback),
            OllamaWireResponse,
        )
        try:
            return parsed.to_draft()
        except Exception as exc:
            raise OpenAIGenerationError(
                f"ollama returned a draft that failed local validation: {exc}"
            ) from exc

    def _request_model(
        self, system_prompt: str, user_prompt: str, schema: type[BaseModel]
    ) -> QuestionDraftResponse:
        try:
            content = self._ollama_request(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                schema,
            )
            if not content:
                raise ValueError("empty response")
            wire_response = schema.model_validate(json.loads(content))
            return QuestionDraftResponse.model_validate(
                normalize_plain_response(wire_response.model_dump())
            )
        except Exception as exc:
            raise OpenAIGenerationError(
                f"ollama returned invalid question JSON: {exc}"
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
            timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
            with urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            return body["message"]["content"]
        except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc


class OllamaWireResponse(BaseModel):
    """Flat Ollama wire contract; semantic validation happens locally."""

    model_config = ConfigDict(extra="forbid")
    code: str
    entry_function: str
    inputs: dict[str, object]
    question: str
    distractors: list[object]
    distractor_reasons: list[str]
    question_type: str


_OLLAMA_SYSTEM_PROMPT = """\
Generate exactly one Python multiple-choice return-value question.
Return one JSON object with exactly these keys: code, entry_function, inputs,
question, distractors, distractor_reasons, question_type.
Use plain JSON values: inputs must be an object mapping function argument names to
their values, and distractors must be an array of raw JSON values. Do not wrap
values in kind/scalar/items/properties fields. question_type must be mcq.
Use only module-level functions, expressions, assignments, if statements, and for
loops. Do not use imports, attributes, classes, decorators, recursion,
comprehensions, while loops, lambdas, exceptions, file access, networking, input,
eval, or exec. Generate exactly the requested number of distinct conceptual
distractors and one reason per distractor. Return no markdown.
"""
