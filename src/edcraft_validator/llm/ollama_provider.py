import copy
import json
import math
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from edcraft_validator.llm.llm_contracts import (
    ModelTurn,
    StructuredGenerationRequest,
    ToolCall,
)
from edcraft_validator.llm.llm_errors import (
    GenerationError,
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.llm.tool_context import generation_messages


class OllamaProvider:
    """Structured generation through Ollama's native endpoint."""

    def __init__(self, *, model: str | None = None) -> None:
        self.provider = "ollama"
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"
        self._options = {"temperature": _temperature(), "num_predict": _num_predict()}
        self._timeout = _timeout_seconds()
        self._think = _thinking()

    def generation_settings(self) -> dict:
        return {
            "options": copy.deepcopy(self._options),
            "timeout_seconds": self._timeout,
            "think": self._think,
        }

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT:
        try:
            content = self._ollama_request(
                generation_messages(request),
                request.response_model.model_json_schema(),
            )
            if not content:
                raise GenerationResponseError("Ollama returned an empty response")
            return request.response_model.model_validate_json(content)
        except GenerationError:
            raise
        except ValidationError as exc:
            if any(error["type"] == "json_invalid" for error in exc.errors()):
                raise GenerationResponseError(
                    f"Ollama returned malformed JSON: {exc}"
                ) from exc
            raise GenerationSchemaError(
                f"Ollama result failed local schema validation: {exc}"
            ) from exc

    def _ollama_request(
        self, messages: list[dict[str, str]], schema: dict[str, object]
    ) -> str:
        # Ollama's format constrains JSON syntax; the prompt also needs to show
        # the field meanings, especially when a revision uses a different schema.
        messages = copy.deepcopy(messages) + [
            {
                "role": "user",
                "content": (
                    "Satisfy the request and any check feedback above. Return only "
                    "a JSON object matching this response schema:\n"
                    + json.dumps(schema)
                ),
            }
        ]
        return self._chat(messages, schema=schema)["content"]

    def tool_turn(self, messages, tools) -> ModelTurn:
        message = self._chat(messages, tools=tools)
        try:
            return ModelTurn(
                content=message.get("content", ""),
                calls=[
                    ToolCall(
                        id=str(uuid.uuid4()),
                        name=call["function"]["name"],
                        arguments_json=json.dumps(call["function"]["arguments"]),
                    )
                    for call in message.get("tool_calls", [])
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GenerationResponseError(
                "Ollama returned an invalid tool turn"
            ) from exc

    def _chat(self, messages, *, schema=None, tools=None):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        native_messages = copy.deepcopy(messages)
        for message in native_messages:
            if message.get("role") == "tool":
                message.pop("tool_call_id", None)
                message["tool_name"] = message.pop("name")
            for call in message.get("tool_calls", []):
                call.pop("id", None)
                call["function"]["arguments"] = json.loads(
                    call["function"]["arguments"]
                )
        payload = {
            "model": self.model,
            "messages": native_messages,
            "stream": False,
            "options": self._options,
        }
        if self._think is not None:
            payload["think"] = self._think
        if schema is not None:
            payload["format"] = schema
        if tools:
            payload["tools"] = tools
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout = self._timeout
            with urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            if body.get("done_reason") == "length":
                raise GenerationResponseError(
                    "Ollama exhausted OLLAMA_NUM_PREDICT before completing its "
                    "response. Disable thinking with OLLAMA_THINK=false "
                    "or increase the output budget."
                )
            return body["message"]
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


def _thinking() -> bool | str | None:
    raw = os.getenv("OLLAMA_THINK", "false").strip().lower()
    values = {
        "false": False,
        "true": True,
        "default": None,
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    if raw not in values:
        raise GenerationError(
            "OLLAMA_THINK must be false, true, default, low, medium, or high"
        )
    return values[raw]


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
