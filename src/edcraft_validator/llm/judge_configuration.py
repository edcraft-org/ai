"""Validated judge settings loaded once by a CLI, server or worker boundary."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edcraft_validator.llm.llm_contracts import ModelProvider, TemplateProviderSelection
from edcraft_validator.llm.provider_registry import (
    available_model_providers,
    create_model_provider,
)

DEFAULT_RELEVANCE_THRESHOLD = 0.9223792980579683


class JudgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    provider: str = Field(default="soclaas", min_length=1)
    model: str = Field(default="x-test-3", min_length=1)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    decision_threshold: float = Field(default=0.7, ge=0, le=1)
    reasoning_threshold: float = Field(default=0.8, ge=0, le=1)
    relevance_threshold: float = Field(default=DEFAULT_RELEVANCE_THRESHOLD, ge=0, le=1)
    decision_timeout_seconds: float = Field(default=35, gt=0)

    @field_validator("provider")
    @classmethod
    def known_provider(cls, value: str) -> str:
        if value not in available_model_providers():
            raise ValueError("Unsupported judge provider")
        return value


def load_judge_settings(environ: Mapping[str, str] | None = None) -> JudgeSettings:
    env = os.environ if environ is None else environ
    return JudgeSettings.model_validate(
        {
            "provider": env.get("EDCRAFT_JUDGE_PROVIDER", "soclaas").strip(),
            "model": env.get("EDCRAFT_JUDGE_MODEL", "x-test-3").strip(),
            "reasoning_effort": env.get(
                "EDCRAFT_JUDGE_REASONING_EFFORT", "medium"
            ).strip(),
            "relevance_threshold": env.get(
                "EDCRAFT_RELEVANCE_THRESHOLD", str(DEFAULT_RELEVANCE_THRESHOLD)
            ),
        }
    )


def configured_judge_provider(settings: JudgeSettings | None = None) -> ModelProvider:
    selected = settings if settings is not None else load_judge_settings()
    return create_model_provider(
        TemplateProviderSelection(provider=selected.provider, model=selected.model)
    )
