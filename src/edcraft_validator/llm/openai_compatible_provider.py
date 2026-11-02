import copy
import json
import math
import os
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.llm_errors import (
    GenerationError,
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.llm.tool_context import (
    constrained_check_plan,
    generation_messages,
)
from edcraft_validator.llm.usage import TokenUsage

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_SOCLAAS_MODEL = "x-test-1"
OpenAIGenerationError = GenerationError


class OpenAICompatibleProvider:
    """Structured generation through an OpenAI-compatible API."""

    def __init__(
        self, provider: str, client: Any | None = None, *, model: str | None = None
    ) -> None:
        if provider not in {"openai", "soclaas"}:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider = provider
        self._owns_client = client is None
        if client is None:
            api_key = _api_key(provider)
            if api_key is None:
                variable = _variable(provider, "API_KEY")
                raise OpenAIGenerationError(f"{variable} is not configured")
            client = OpenAI(
                api_key=api_key,
                base_url=_base_url(provider),
                timeout=_timeout_seconds(provider),
                max_retries=_max_retries(provider),
            )
        self.client = client
        self.model = model or _model(provider)
        self.last_usage = TokenUsage()
        soclaas = provider == "soclaas"
        self._response_format = _response_format(provider)
        self._generation_max_tokens = _positive_int_setting(
            provider, "GENERATION_MAX_TOKENS", 16384 if soclaas else None
        )
        self._reasoning_effort = _reasoning_effort(provider)

    def generation_settings(self) -> dict[str, Any]:
        # Sampling parameters are deliberately omitted from API requests. Do not
        # claim a temperature/seed for defaults controlled by the remote provider.
        timeout = getattr(self.client, "timeout", None)
        if timeout is not None and not isinstance(timeout, int | float):
            timeout = str(timeout)
        settings = {
            "sampling": "provider_defaults",
            "response_format": self._response_format,
            "strict": self._response_format == "json_schema",
            "timeout_seconds": timeout,
            "max_retries": getattr(self.client, "max_retries", None),
        }
        if self._generation_max_tokens is not None:
            settings["generation_max_tokens"] = self._generation_max_tokens
        if self._reasoning_effort is not None:
            settings["reasoning_effort"] = self._reasoning_effort
        elif self.provider == "soclaas":
            settings["reasoning_effort"] = "provider_default"
        return settings

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def generate[ProposalT: BaseModel](
        self, request: StructuredGenerationRequest[ProposalT]
    ) -> ProposalT:
        """Generate any domain proposal described by the supplied request."""
        self.last_usage = TokenUsage()
        try:
            wire_model = (
                constrained_check_plan(
                    request.response_model,
                    request.offered_tool_names,
                    request.check_argument_models,
                )
                if request.offered_tool_names
                else request.response_model
            )
            schema = wire_model.model_json_schema()
            messages = generation_messages(request)
            response_format = {"type": self._response_format}
            if self._response_format == "json_schema":
                response_format["json_schema"] = {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": schema,
                }
            else:
                # JSON mode constrains syntax; local validation enforces the schema.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Satisfy the request and any check feedback above. "
                            "Return only one JSON object matching this response "
                            "schema. Preserve string contents, including line breaks "
                            "and indentation, using valid JSON escaping.\n"
                            + json.dumps(schema)
                        ),
                    }
                )
            kwargs = {
                "model": self.model,
                "messages": copy.deepcopy(messages),
                "response_format": response_format,
            }
            effort = request.reasoning_effort or self._reasoning_effort
            if effort is not None:
                kwargs["reasoning_effort"] = effort
            if self._generation_max_tokens is not None:
                kwargs["max_tokens"] = self._generation_max_tokens
            response = self.client.chat.completions.create(**kwargs)
            self._record_usage(response)
            if getattr(response.choices[0], "finish_reason", None) == "length":
                raise GenerationResponseError(
                    f"{self.provider} generation exhausted its output budget"
                )
            content = response.choices[0].message.content
            if not content:
                raise GenerationResponseError(
                    f"{self.provider} returned an empty response"
                )
            result = wire_model.model_validate_json(content)
            if wire_model is not request.response_model:
                result = request.response_model.model_validate_json(
                    result.model_dump_json()
                )
            return result
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

    def decide(self, messages, labels):
        """One forced classification call; no reasoning or structured generation."""
        from edcraft_validator.llm.forced_decision import (
            DECISION_REQUEST_OPTIONS,
            decision_from_response,
        )

        self.last_usage = TokenUsage()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=copy.deepcopy(messages),
                **DECISION_REQUEST_OPTIONS,
            )
            self._record_usage(response)
            return decision_from_response(response, labels)
        except APITimeoutError as exc:
            raise GenerationTimeoutError("Decision request timed out") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise GenerationTransportError("Decision request failed") from exc

    def _record_usage(self, response):
        usage = getattr(response, "usage", None)
        self.last_usage = TokenUsage.from_counts(
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )


def _variable(provider: str, name: str) -> str:
    """Both providers configure the same options under their own prefix."""
    return f"{provider.upper()}_{name}"


def _api_key(provider: str) -> str | None:
    variable = _variable(provider, "API_KEY")
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


def _base_url(provider: str) -> str | None:
    value = os.getenv(_variable(provider, "BASE_URL"))
    return value.strip() if value else None


def _model(provider: str) -> str:
    configured = os.getenv(_variable(provider, "MODEL"), "").strip()
    if configured:
        return configured
    return DEFAULT_OPENAI_MODEL if provider == "openai" else DEFAULT_SOCLAAS_MODEL


def _timeout_seconds(provider: str) -> float:
    variable = _variable(provider, "TIMEOUT_SECONDS")
    raw_value = os.getenv(variable, "300" if provider == "soclaas" else "120").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise OpenAIGenerationError(f"{variable} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise OpenAIGenerationError(f"{variable} must be greater than zero")
    return value


def _max_retries(provider: str) -> int:
    variable = _variable(provider, "MAX_RETRIES")
    raw_value = os.getenv(variable, "1").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise OpenAIGenerationError(f"{variable} must be an integer") from exc
    if not 0 <= value <= 5:
        raise OpenAIGenerationError(f"{variable} must be between 0 and 5")
    return value


def _positive_int_setting(
    provider: str, name: str, default: int | None = None
) -> int | None:
    variable = _variable(provider, name)
    raw = os.getenv(variable)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise OpenAIGenerationError(f"{variable} must be an integer") from exc
    if value < 1:
        raise OpenAIGenerationError(f"{variable} must be greater than zero")
    return value


def _response_format(provider: str) -> str:
    variable = _variable(provider, "RESPONSE_FORMAT")
    value = os.getenv(variable, "json_schema").strip()
    if value not in {"json_object", "json_schema"}:
        raise OpenAIGenerationError(f"{variable} must be json_object or json_schema")
    return value


def _reasoning_effort(provider: str) -> str | None:
    value = os.getenv(_variable(provider, "REASONING_EFFORT"), "default")
    value = value.strip() or "default"
    return None if value == "default" else value


class OpenAIProvider(OpenAICompatibleProvider):
    """Structured generation through OpenAI's API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("openai", client, model=model)


class SocLaasProvider(OpenAICompatibleProvider):
    """Structured generation through the SocLaas API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("soclaas", client, model=model)
