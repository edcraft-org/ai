import copy
import math
import os
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
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

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
OpenAIGenerationError = GenerationError


class OpenAICompatibleProvider:
    """Structured generation through an OpenAI-compatible API."""

    def __init__(
        self, provider: str, client: Any | None = None, *, model: str | None = None
    ) -> None:
        if provider not in {"openai", "soclaas"}:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider = provider
        if client is None:
            api_key = _api_key(provider)
            if api_key is None:
                variable = _api_key_variable(provider)
                raise OpenAIGenerationError(f"{variable} is not configured")
            client = OpenAI(
                api_key=api_key,
                base_url=_base_url(provider),
                timeout=_timeout_seconds(provider),
                max_retries=_max_retries(provider),
            )
        self.client = client
        self.model = model or _model(provider)

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT:
        """Generate any domain proposal described by the supplied request."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=_wire_messages(generation_messages(request)),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.schema_name,
                        "strict": True,
                        "schema": request.response_model.model_json_schema(),
                    },
                },
            )
            content = response.choices[0].message.content
            if not content:
                raise GenerationResponseError(
                    f"{self.provider} returned an empty response"
                )
            return request.response_model.model_validate_json(content)
        except GenerationError:
            raise
        except APITimeoutError as exc:
            raise GenerationTimeoutError(f"{self.provider} request timed out") from exc
        except APIConnectionError as exc:
            raise GenerationTransportError(
                f"{self.provider} connection failed: {exc}"
            ) from exc
        except APIStatusError as exc:
            raise GenerationTransportError(
                f"{self.provider} HTTP request failed with status {exc.status_code}"
            ) from exc
        except ValidationError as exc:
            if any(error["type"] == "json_invalid" for error in exc.errors()):
                raise GenerationResponseError(
                    f"{self.provider} returned malformed JSON: {exc}"
                ) from exc
            raise GenerationSchemaError(
                f"{self.provider} response failed local schema validation: {exc}"
            ) from exc
        except Exception as exc:
            raise OpenAIGenerationError(
                f"{self.provider} failed to generate a structured result: {exc}"
            ) from exc

    def tool_turn(self, messages, tools) -> ModelTurn:
        """Translate native function calls; execution remains application-owned."""
        try:
            kwargs = {"model": self.model, "messages": _wire_messages(messages)}
            if tools:
                kwargs.update(
                    tools=_strict_tools(tools),
                    tool_choice="required",
                    parallel_tool_calls=False,
                )
            response = self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            return ModelTurn(
                content=message.content or "",
                calls=[
                    ToolCall(
                        id=call.id,
                        name=call.function.name,
                        arguments_json=call.function.arguments,
                    )
                    for call in (message.tool_calls or [])
                ],
            )
        except APITimeoutError as exc:
            raise GenerationTimeoutError(
                f"{self.provider} tool turn timed out"
            ) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise GenerationTransportError(f"{self.provider} tool turn failed") from exc
        except Exception as exc:
            raise GenerationResponseError(
                f"{self.provider} returned an invalid tool turn"
            ) from exc


def _api_key(provider: str) -> str | None:
    variable = _api_key_variable(provider)
    raw_value = os.getenv(variable)
    if raw_value is None:
        return None

    value = raw_value.strip()
    if not value:
        return None
    if not value.isascii() or any(character.isspace() for character in value):
        raise OpenAIGenerationError(
            f"{variable} contains invalid whitespace or non-ASCII characters"
        )
    return value


def _api_key_variable(provider: str) -> str:
    return {
        "soclaas": "SOCLAAS_API_KEY",
        "openai": "OPENAI_API_KEY",
    }[provider]


def _base_url(provider: str) -> str | None:
    value = {
        "soclaas": os.getenv("SOCLAAS_BASE_URL"),
        "openai": os.getenv("OPENAI_BASE_URL"),
    }[provider]
    return value.strip() if value else None


def _model(provider: str) -> str:
    variable = {
        "soclaas": "SOCLAAS_MODEL",
        "openai": "OPENAI_MODEL",
    }[provider]
    configured = os.getenv(variable, "").strip()
    if configured:
        return configured
    if provider == "openai":
        return DEFAULT_OPENAI_MODEL
    raise OpenAIGenerationError(f"{variable} is not configured")


def _timeout_seconds(provider: str) -> float:
    variable = {
        "soclaas": "SOCLAAS_TIMEOUT_SECONDS",
        "openai": "OPENAI_TIMEOUT_SECONDS",
    }[provider]
    raw_value = os.getenv(variable, "120").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise OpenAIGenerationError(f"{variable} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise OpenAIGenerationError(f"{variable} must be greater than zero")
    return value


def _max_retries(provider: str) -> int:
    variable = {
        "soclaas": "SOCLAAS_MAX_RETRIES",
        "openai": "OPENAI_MAX_RETRIES",
    }[provider]
    raw_value = os.getenv(variable, "1").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise OpenAIGenerationError(f"{variable} must be an integer") from exc
    if not 0 <= value <= 5:
        raise OpenAIGenerationError(f"{variable} must be between 0 and 5")
    return value


class OpenAIProvider(OpenAICompatibleProvider):
    """Structured generation through OpenAI's API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("openai", client, model=model)


class SocLaasProvider(OpenAICompatibleProvider):
    """Structured generation through the SocLaas API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("soclaas", client, model=model)


def _wire_messages(messages):
    wire = copy.deepcopy(messages)
    for message in wire:
        if message.get("role") == "tool":
            message.pop("name", None)
    return wire


def _strict_tools(tools):
    """Use strict arguments when MCP's projected schema already satisfies it."""
    wire = copy.deepcopy(tools)
    for tool in wire:
        schema = tool["function"]["parameters"]
        if _closed_schema(schema):
            tool["function"]["strict"] = True
    return wire


def _closed_schema(value):
    if isinstance(value, list):
        return all(_closed_schema(item) for item in value)
    if not isinstance(value, dict):
        return True
    if value.get("type") == "object" or "properties" in value:
        if value.get("additionalProperties") is not False or set(
            value.get("required", [])
        ) != set(value.get("properties", {})):
            return False
    return all(_closed_schema(item) for item in value.values())
