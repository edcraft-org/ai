from edcraft_validator.generation.observability import (
    AttemptTelemetry,
    GenerationMetrics,
    provider_metadata,
)


def telemetry(**changes: object) -> AttemptTelemetry:
    # Use a small baseline so each metrics test changes only one concern.
    data: dict[str, object] = {
        "provider": "ollama",
        "model": "qwen2.5",
        "generation_duration_ms": 10.0,
        "validation_duration_ms": 2.0,
        "status": "invalid",
        "issue_codes": ("DUPLICATE_DISTRACTOR",),
    }
    data.update(changes)
    return AttemptTelemetry(**data)


def test_metrics_aggregate_attempts_and_issue_codes() -> None:
    # Metrics should count attempts, providers, durations, and repeated issue codes.
    metrics = GenerationMetrics()
    metrics.record_attempt(telemetry())
    metrics.record_attempt(telemetry(status="valid", issue_codes=()))
    metrics.record_outcome("accepted")

    assert metrics.snapshot() == {
        "attempts_total": 2,
        "outcomes": {"accepted": 1},
        "issue_codes": {"DUPLICATE_DISTRACTOR": 1},
        "provider_requests": {"ollama": 2},
        "generation_duration_ms": 20.0,
        "validation_duration_ms": 4.0,
    }


def test_provider_metadata_reads_adapter_identity() -> None:
    # Adapters with provider/model attributes should supply stable log metadata.
    class Adapter:
        provider = "soclaas"
        model = "test-model"

    assert provider_metadata(Adapter()) == ("soclaas", "test-model")


def test_provider_metadata_has_safe_fallbacks() -> None:
    # Test doubles without provider metadata should still produce usable telemetry.
    class TestGenerator:
        pass

    assert provider_metadata(TestGenerator()) == ("TestGenerator", None)
