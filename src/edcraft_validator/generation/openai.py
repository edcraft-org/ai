import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.generation.provider import (
    QuestionDraftResponse,
    TaggedInput,
    TaggedJsonValue,
    build_prompt,
)
from edcraft_validator.models import ValidationReport

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
OpenAIJsonValue = TaggedJsonValue
OpenAIInput = TaggedInput
OpenAIQuestionDraftResponse = QuestionDraftResponse


class OpenAIGenerationError(RuntimeError):
    """Raised when a provider does not return a usable question draft."""


class OpenAICompatibleQuestionGenerator:
    """Generate a draft through an OpenAI-compatible chat-completions API."""

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

    def generate_draft(
        self, request: GenerationRequest, *, feedback: ValidationReport | None = None
    ) -> QuestionDraft:
        parsed = self._request_model(
            _SYSTEM_PROMPT, build_prompt(request, feedback), QuestionDraftResponse
        )
        try:
            return parsed.to_draft()
        except Exception as exc:
            raise OpenAIGenerationError(
                f"{self.provider} returned a draft that failed local validation: {exc}"
            ) from exc

    def _request_model(
        self, system_prompt: str, user_prompt: str, schema: type[BaseModel]
    ) -> QuestionDraftResponse:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "question_draft",
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    },
                },
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("empty response")
            return schema.model_validate_json(content)
        except Exception as exc:
            raise OpenAIGenerationError(
                f"{self.provider} returned invalid question JSON: {exc}"
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


_SYSTEM_PROMPT = """\
Generate exactly one Python multiple-choice return-value question with
conceptual distractors.
Use only the validator's safe subset: module-level functions, expressions, assignments,
if statements, and for loops. Do not use imports, attributes, classes, decorators,
recursion, comprehensions, while loops, lambdas, exceptions, file access, networking,
input, eval, or exec.
Encode every input and distractor as a tagged value: scalar values use kind=scalar,
lists use kind=list with tagged items, and objects use kind=object with tagged key/value
properties. Include scalar, items, and properties in every tagged value; unused fields
must be null or empty arrays as appropriate. Return exactly the keys code,
entry_function,
inputs, question, distractors, distractor_reasons, and question_type. Generate exactly
the requested number of distinct conceptual distractors and one reason per distractor.
question_type must be exactly mcq. Return one JSON object with no markdown.
"""

_build_prompt = build_prompt
