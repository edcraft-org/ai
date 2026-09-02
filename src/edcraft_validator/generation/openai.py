import os
from typing import Any

from openai import OpenAI

from edcraft_validator.domains.code.templates import (
    CODE_TEMPLATE_SYSTEM_PROMPT,
    CodeTemplateProposal,
    build_template_prompt,
    parse_code_template_proposal,
)
from edcraft_validator.generation.base import GenerationError
from edcraft_validator.generation.models import TemplateAuthoringRequest

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
            client = OpenAI(api_key=api_key, base_url=_base_url(provider))
        self.client = client
        self.model = model or _model(provider)

    def generate_proposal(
        self, request: TemplateAuthoringRequest
    ) -> CodeTemplateProposal:
        """Ask the provider for the judgment-bearing template fields."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT},
                    {"role": "user", "content": build_template_prompt(request)},
                ],
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
                raise ValueError("empty response")
            return parse_code_template_proposal(content)
        except Exception as exc:
            raise OpenAIGenerationError(
                f"{self.provider} failed to generate a question template: {exc}"
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


class OpenAITemplateGenerator(OpenAICompatibleTemplateGenerator):
    """Author reusable templates through OpenAI's API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("openai", client, model=model)


class SocLaasTemplateGenerator(OpenAICompatibleTemplateGenerator):
    """Author templates through the SocLaas OpenAI-compatible API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("soclaas", client, model=model)
