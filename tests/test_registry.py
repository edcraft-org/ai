from pathlib import Path

import pytest

from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.registry import (
    available_providers,
    available_template_providers,
    create_generator,
    create_template_generator,
    register_provider,
)


def test_registry_creates_builtin_fake_provider() -> None:
    generator = create_generator("fake", examples_dir=Path("examples"))

    assert isinstance(generator, FakeQuestionGenerator)
    assert "openai" in available_providers()
    assert "ollama" in available_providers()


def test_registry_supports_extension_without_cli_changes() -> None:
    class CustomGenerator:
        provider = "custom"
        model = "custom-model"

    register_provider("custom", CustomGenerator)

    assert isinstance(create_generator("custom"), CustomGenerator)


def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported provider"):
        create_generator("missing")


def test_registry_exposes_ai_template_providers() -> None:
    assert "fake" not in available_template_providers()
    assert "openai" in available_template_providers()
    assert create_template_generator("ollama").provider == "ollama"
