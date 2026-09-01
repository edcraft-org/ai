from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttemptTelemetry:
    """Internal metadata for diagnosing one generation attempt."""

    provider: str
    model: str | None
    generation_duration_ms: float
    validation_duration_ms: float
    status: str
    issue_codes: tuple[str, ...]


@dataclass
class GenerationMetrics:
    """Small in-memory metrics collector for one application process."""

    attempts_total: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    issue_codes: Counter[str] = field(default_factory=Counter)
    provider_requests: Counter[str] = field(default_factory=Counter)
    generation_duration_ms: float = 0.0
    validation_duration_ms: float = 0.0

    def record_attempt(self, telemetry: AttemptTelemetry) -> None:
        self.attempts_total += 1
        self.provider_requests[telemetry.provider] += 1
        self.generation_duration_ms += telemetry.generation_duration_ms
        self.validation_duration_ms += telemetry.validation_duration_ms
        self.issue_codes.update(telemetry.issue_codes)

    def record_outcome(self, status: str) -> None:
        self.outcomes[status] += 1

    def snapshot(self) -> dict[str, object]:
        """Return JSON-serializable counters for logs or a metrics endpoint."""
        return {
            "attempts_total": self.attempts_total,
            "outcomes": dict(self.outcomes),
            "issue_codes": dict(self.issue_codes),
            "provider_requests": dict(self.provider_requests),
            "generation_duration_ms": self.generation_duration_ms,
            "validation_duration_ms": self.validation_duration_ms,
        }


def provider_metadata(generator: object) -> tuple[str, str | None]:
    """Read optional provider metadata without coupling the service to adapters."""
    provider = getattr(generator, "provider", None)
    if not isinstance(provider, str):
        provider = generator.__class__.__name__.removesuffix("QuestionGenerator")
    model = getattr(generator, "model", None)
    return provider, model if isinstance(model, str) else None
