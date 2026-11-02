"""Forced label decisions with first-token probability evidence and no rationale."""

import math
from functools import partial

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.llm.judging import run_judge
from edcraft_validator.llm.llm_contracts import supports_decisions
from edcraft_validator.llm.llm_errors import GenerationResponseError
from edcraft_validator.llm.usage import close_provider

DECISION_REQUEST_OPTIONS = {
    "temperature": 0,
    "max_tokens": 16,
    "reasoning_effort": "none",
    "logprobs": True,
    "top_logprobs": 20,
}


def decision_settings(provider, labels):
    settings = provider.generation_settings()
    return {
        **{
            key: settings[key]
            for key in ("timeout_seconds", "max_retries")
            if key in settings
        },
        **DECISION_REQUEST_OPTIONS,
        "response_format": "text",
        "labels": list(labels),
    }


class ClassDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    label: str
    distribution: dict[str, float]
    confidence: float = Field(ge=0, le=1)
    served_model: str | None = None

    @model_validator(mode="after")
    def validate_distribution(self):
        if (
            not self.distribution
            or any(not 0 <= p <= 1 for p in self.distribution.values())
            or not math.isclose(sum(self.distribution.values()), 1, abs_tol=1e-8)
            or self.label not in self.distribution
            or self.label != max(self.distribution, key=self.distribution.get)
            or not math.isclose(self.confidence, self.distribution[self.label])
        ):
            raise ValueError("Invalid decision distribution")
        return self


def decision_from_response(response, labels):
    """Normalize observed top-k token mass over allowed labels, not all tokens."""
    try:
        choice = response.choices[0]
        content = (choice.message.content or "").strip().lower().removesuffix(".")
        if choice.finish_reason != "stop" or content not in labels:
            raise ValueError("Decision did not return exactly one allowed label")
        first = choice.logprobs.content[0]
        masses = {label: [] for label in labels}
        for token in first.top_logprobs:
            label = token.token.strip().lower().removesuffix(".")
            if label in masses:
                if not math.isfinite(token.logprob) or token.logprob > 0:
                    raise ValueError("Invalid token probability")
                masses[label].append(token.logprob)
        observed = [p for values in masses.values() for p in values]
        if not observed:
            raise ValueError("No allowed labels in token probabilities")
        peak = max(observed)
        weights = {
            label: sum(math.exp(p - peak) for p in values)
            for label, values in masses.items()
        }
        total = sum(weights.values())
        distribution = {label: weight / total for label, weight in weights.items()}
        label = max(distribution, key=distribution.get)
        if content != label:
            raise ValueError("Returned label disagrees with token probabilities")
        return ClassDecision(
            label=label,
            confidence=distribution[label],
            distribution=distribution,
            served_model=getattr(response, "model", None),
        )
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise GenerationResponseError("Invalid decision response or logprobs") from exc


class DecisionAdapter:
    """Expose a decision-capable provider to the common measured judge runner."""

    def __init__(self, provider_factory, labels):
        self.delegate = provider_factory()
        if not supports_decisions(self.delegate):
            raise ValueError("Provider does not support token-probability decisions")
        self.provider, self.model = self.delegate.provider, self.delegate.model
        self.labels = labels

    def generation_settings(self):
        return decision_settings(self.delegate, self.labels)

    @property
    def last_usage(self):
        return getattr(self.delegate, "last_usage", None)

    def close(self):
        close_provider(self.delegate)

    def generate(self, request):
        result = ClassDecision.model_validate(
            self.delegate.decide(request.messages, self.labels).model_dump()
        )
        if set(result.distribution) != set(self.labels):
            raise GenerationResponseError("Decision labels do not match request")
        return result


async def run_decision(request, *, labels, provider_factory, timeout_seconds):
    return await run_judge(
        request,
        provider_factory=partial(DecisionAdapter, provider_factory, labels),
        timeout_seconds=timeout_seconds,
    )


class JudgeProviderSession:
    """Fresh fallback transport; structured-only injected providers stay compatible."""

    def __init__(self, factory):
        self.factory = factory
        self.first = None

    def decision_provider(self):
        if self.first is None:
            self.first = self.factory()
        return self.first

    def reasoning_provider(self):
        provider = self.decision_provider()
        if supports_decisions(provider):
            return self.factory()
        return provider
