"""Model-provider wiring for one worker job.

This intentionally mirrors ``edcraft_backend/services/ai_authoring_judge.py``
without importing backend code: the context endpoint supplies credentials and
the worker owns their lifecycle for exactly one job.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.llm.decision import ConfiguredDecisionProvider
from edcraft_validator.llm.judge_configuration import JudgeSettings, load_judge_settings
from edcraft_validator.llm.llm_contracts import (
    ModelProvider,
    StructuredGenerationRequest,
    supports_decisions,
)
from edcraft_validator.llm.openai_compatible_provider import (
    OpenAIProvider,
    SocLaasProvider,
)
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server

DEFAULT_TIMEOUT_SECONDS = {
    "soclaas": 600.0,
    "openai": 120.0,
}

ProviderName = Literal["soclaas", "openai"]


class ProviderPlan(BaseModel):
    """One role's non-persisted credentials from the context response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    model: str = Field(min_length=1)
    api_key: str = Field(min_length=1, repr=False)
    base_url: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)

    @property
    def effective_timeout_seconds(self) -> float:
        if self.timeout_seconds is not None:
            return self.timeout_seconds
        return DEFAULT_TIMEOUT_SECONDS[self.provider]


class WorkerPlan(BaseModel):
    """Author and advisory roles for exactly one authoring job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    author: ProviderPlan
    difficulty: ProviderPlan
    relevance: ProviderPlan


class SelectedModelDecisionProvider(ConfiguredDecisionProvider):
    """Relevance classifier that reuses the model selected for the check."""

    def __init__(self, settings: JudgeSettings, provider: ModelProvider) -> None:
        if not supports_decisions(provider):
            raise ValueError("Provider does not support token-probability decisions")
        self.settings = settings
        self.delegate = provider
        self.provider = provider.provider
        self.model = provider.model
        self.threshold = settings.relevance_threshold
        self.served_model = None


class ManagedProvider:
    """Adapt a validator provider and own its OpenAI client lifecycle."""

    def __init__(
        self,
        delegate: ModelProvider,
        client: OpenAI,
        *,
        provider: str,
        model: str,
    ) -> None:
        self._delegate = delegate
        self._client = client
        self.provider = provider
        self.model = model

    def generation_settings(self) -> dict[str, Any]:
        return self._delegate.generation_settings()

    def generate(self, request: StructuredGenerationRequest[Any]) -> Any:
        return self._delegate.generate(request)

    def decide(self, messages: list[dict[str, Any]], labels: tuple[str, ...]) -> Any:
        decide = getattr(self._delegate, "decide", None)
        if not callable(decide):
            raise ValueError("Provider does not support token-probability decisions")
        return decide(messages, labels)

    @property
    def last_usage(self) -> Any:
        return getattr(self._delegate, "last_usage", None)

    def close(self) -> None:
        self._client.close()


def judge_settings_for(provider: str, model: str) -> JudgeSettings:
    """Keep server thresholds and reasoning effort while replacing the model."""
    return load_judge_settings().model_copy(
        update={"provider": provider, "model": model}
    )


def build_provider(
    plan: ProviderPlan,
    *,
    client_factory: Callable[..., Any] = OpenAI,
) -> ManagedProvider:
    """Build one role's provider from the credentials supplied in the context."""
    client = client_factory(
        api_key=plan.api_key,
        base_url=plan.base_url,
        timeout=plan.effective_timeout_seconds,
        max_retries=1,
    )
    try:
        if plan.provider == "soclaas":
            delegate: ModelProvider = SocLaasProvider(client=client, model=plan.model)
        elif plan.provider == "openai":
            delegate = OpenAIProvider(client=client, model=plan.model)
        else:  # pragma: no cover - ProviderPlan already rejects other names
            raise ValueError(f"Unsupported provider: {plan.provider}")
    except Exception:
        client.close()
        raise
    return ManagedProvider(
        delegate,
        client,
        provider=plan.provider,
        model=plan.model,
    )


def build_model_tool_client(
    *,
    difficulty: ProviderPlan,
    relevance: ProviderPlan,
) -> FastMcpToolClient:
    """Build validation tools with separately selected advisory models."""
    difficulty_settings = judge_settings_for(difficulty.provider, difficulty.model)
    relevance_settings = judge_settings_for(relevance.provider, relevance.model)
    return FastMcpToolClient(
        create_validation_server(
            judge_settings=difficulty_settings,
            difficulty_provider_factory=lambda: build_provider(difficulty),
            decision_provider_factory=lambda: SelectedModelDecisionProvider(
                relevance_settings, build_provider(relevance)
            ),
        )
    )
