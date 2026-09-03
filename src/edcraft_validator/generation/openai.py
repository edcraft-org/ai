import json
import math
import os
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from edcraft_validator.domains.code.templates import (
    CODE_TEMPLATE_PROMPT_VERSION,
    CODE_TEMPLATE_SYSTEM_PROMPT,
    CodeTemplateProposal,
    build_template_prompt,
    parse_code_template_proposal,
)
from edcraft_validator.generation.base import (
    GenerationError,
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
    build_prompt_metadata,
)
from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplatePromptMetadata,
)

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
OpenAIGenerationError = GenerationError


class OpenAICompatibleTemplateGenerator:
    """Author templates through an OpenAI-compatible chat-completions API."""

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

    def generate_proposal(
        self, request: TemplateAuthoringRequest
    ) -> CodeTemplateProposal:
        """Ask the provider for the judgment-bearing template fields."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._messages(request),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "question_template",
                        "strict": True,
                        "schema": CodeTemplateProposal.model_json_schema(),
                    },
                },
            )
            content = response.choices[0].message.content
            if not content:
                raise GenerationResponseError(
                    f"{self.provider} returned an empty response"
                )
            return parse_code_template_proposal(content)
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
        except (json.JSONDecodeError, ValidationError) as exc:
            raise GenerationSchemaError(
                f"{self.provider} response failed local schema validation: {exc}"
            ) from exc
        except Exception as exc:
            raise OpenAIGenerationError(
                f"{self.provider} failed to generate a question template: {exc}"
            ) from exc

    def prompt_metadata(
        self, request: TemplateAuthoringRequest
    ) -> TemplatePromptMetadata:
        return build_prompt_metadata(
            CODE_TEMPLATE_PROMPT_VERSION, self._messages(request)
        )

    @staticmethod
    def _messages(request: TemplateAuthoringRequest) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": build_template_prompt(request)},
        ]


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


class OpenAITemplateGenerator(OpenAICompatibleTemplateGenerator):
    """Author reusable templates through OpenAI's API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("openai", client, model=model)


class SocLaasTemplateGenerator(OpenAICompatibleTemplateGenerator):
    """Author templates through the SocLaas OpenAI-compatible API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("soclaas", client, model=model)
