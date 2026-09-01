"""Provider registry used by the generation CLI and application code."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from edcraft_validator.generation.base import QuestionGenerator
from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.ollama import OllamaQuestionGenerator
from edcraft_validator.generation.openai import (
    OpenAIQuestionGenerator,
    SocLaasQuestionGenerator,
)

ProviderFactory = Callable[[], QuestionGenerator]

_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "openai": OpenAIQuestionGenerator,
    "ollama": OllamaQuestionGenerator,
    "soclaas": SocLaasQuestionGenerator,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register a provider without changing CLI routing code."""
    if not name or not name.strip():
        raise ValueError("provider name must not be blank")
    if name in {"fake", "openai", "ollama", "soclaas"}:
        raise ValueError(f"provider is already registered: {name}")
    _PROVIDER_FACTORIES[name] = factory


def available_providers() -> tuple[str, ...]:
    """Return providers supported by the default application configuration."""
    return ("fake", *_PROVIDER_FACTORIES.keys())


def create_generator(
    provider: str, *, examples_dir: Path = Path("examples")
) -> QuestionGenerator:
    """Construct a generator from the provider registry."""
    if provider == "fake":
        return FakeQuestionGenerator(examples_dir)
    try:
        factory = _PROVIDER_FACTORIES[provider]
    except KeyError as exc:
        supported = ", ".join(available_providers())
        raise ValueError(
            f"Unsupported provider {provider!r}; choose one of: {supported}"
        ) from exc
    return factory()
