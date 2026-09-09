import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from edcraft_validator.generation.base import (
    GenerationError,
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
    StructuredGenerationRequest,
)


class OllamaProvider:
    """Structured generation through Ollama's native endpoint."""

    def __init__(self, *, model: str | None = None) -> None:
        self.provider = "ollama"
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT:
        try:
            content = self._ollama_request(
                request.messages,
                request.response_model.model_json_schema(),
            )
            if not content:
                raise GenerationResponseError("Ollama returned an empty response")
            return request.parse_response(content)
        except GenerationError:
            raise
        except json.JSONDecodeError as exc:
            raise GenerationResponseError(
                f"Ollama returned malformed JSON: {exc}"
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise GenerationSchemaError(
                f"Ollama result failed local schema validation: {exc}"
            ) from exc

    def _ollama_request(
        self, messages: list[dict[str, str]], schema: dict[str, object]
    ) -> str:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "options": {
                "temperature": _temperature(),
                "num_predict": _num_predict(),
            },
        }
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout = _timeout_seconds()
            with urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            return body["message"]["content"]
        except TimeoutError as exc:
            raise GenerationTimeoutError(
                f"Ollama request timed out after {timeout:g} seconds"
            ) from exc
        except HTTPError as exc:
            raise GenerationTransportError(
                f"Ollama HTTP request failed with status {exc.code}"
            ) from exc
        except URLError as exc:
            raise GenerationTransportError(
                f"Ollama transport request failed: {exc.reason}"
            ) from exc
        except ConnectionError as exc:
            raise GenerationTransportError(
                f"Ollama connection was interrupted: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise GenerationResponseError(
                f"Ollama endpoint returned malformed response JSON: {exc}"
            ) from exc
        except (KeyError, TypeError) as exc:
            raise GenerationResponseError(
                "Ollama endpoint response did not contain message.content"
            ) from exc


def _timeout_seconds() -> float:
    raw_value = os.getenv("OLLAMA_TIMEOUT_SECONDS", "300").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise GenerationError("OLLAMA_TIMEOUT_SECONDS must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise GenerationError("OLLAMA_TIMEOUT_SECONDS must be greater than zero")
    return value


def _temperature() -> float:
    raw_value = os.getenv("OLLAMA_TEMPERATURE", "0").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise GenerationError("OLLAMA_TEMPERATURE must be a number") from exc
    if not math.isfinite(value) or not 0 <= value <= 2:
        raise GenerationError("OLLAMA_TEMPERATURE must be between 0 and 2")
    return value


def _num_predict() -> int:
    raw_value = os.getenv("OLLAMA_NUM_PREDICT", "2048").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise GenerationError("OLLAMA_NUM_PREDICT must be an integer") from exc
    if not 128 <= value <= 4096:
        raise GenerationError("OLLAMA_NUM_PREDICT must be between 128 and 4096")
    return value
