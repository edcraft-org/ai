import os
from typing import Any

from openai import OpenAI

from edcraft_validator.domains.code.templates import (
    CODE_TEMPLATE_SYSTEM_PROMPT,
    CodeQuestionTemplate,
    build_template_prompt,
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
        self.client = client or OpenAI(
            api_key=_api_key(provider), base_url=_base_url(provider)
        )
        self.model = model or _model(provider)

    def generate_template(
        self, request: TemplateAuthoringRequest
    ) -> CodeQuestionTemplate:
        """Ask the provider for one reusable code-question template."""
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
                        "schema": CodeQuestionTemplate.model_json_schema(),
                    },
                },
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("empty response")
            return CodeQuestionTemplate.model_validate_json(content)
        except Exception as exc:
            raise OpenAIGenerationError(
                f"{self.provider} returned invalid question template JSON: {exc}"
            ) from exc


def _api_key(provider: str) -> str | None:
    return {
        "soclaas": os.getenv("SOCLAAS_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
    }[provider]


def _base_url(provider: str) -> str | None:
    return {
        "soclaas": os.getenv("SOCLAAS_BASE_URL"),
        "openai": os.getenv("OPENAI_BASE_URL"),
    }[provider]


def _model(provider: str) -> str:
    return {
        "soclaas": os.getenv("SOCLAAS_MODEL") or DEFAULT_OPENAI_MODEL,
        "openai": os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
    }[provider]


class OpenAITemplateGenerator(OpenAICompatibleTemplateGenerator):
    """Author reusable templates through OpenAI's API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("openai", client, model=model)


class SocLaasTemplateGenerator(OpenAICompatibleTemplateGenerator):
    """Author templates through the SocLaas OpenAI-compatible API."""

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        super().__init__("soclaas", client, model=model)
