"""Application use case for generating and validating one question."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from edcraft_validator.generation.base import (
    QuestionGenerator,
    QuestionValidationBackend,
)
from edcraft_validator.generation.models import GenerationOutcome, GenerationRequest
from edcraft_validator.generation.registry import create_generator
from edcraft_validator.generation.service import DEFAULT_ATTEMPT_LOG, GenerationService
from edcraft_validator.validator import QuestionValidator

GeneratorFactory = Callable[..., QuestionGenerator]
ValidatorFactory = Callable[[], QuestionValidationBackend]


class QuestionGenerationApplication:
    """Wire the current code-domain workflow behind one application API."""

    def __init__(
        self,
        *,
        generator_factory: GeneratorFactory = create_generator,
        validator_factory: ValidatorFactory = QuestionValidator,
    ) -> None:
        self.generator_factory = generator_factory
        self.validator_factory = validator_factory

    def generate(
        self,
        request: GenerationRequest,
        *,
        provider: str,
        examples_dir: Path = Path("examples"),
        attempt_log_path: Path | None = DEFAULT_ATTEMPT_LOG,
        max_attempts: int = 3,
    ) -> GenerationOutcome:
        """Generate one question through the configured provider and validator."""
        generator = self.generator_factory(provider, examples_dir=examples_dir)
        service = GenerationService(
            generator,
            self.validator_factory(),
            max_attempts=max_attempts,
            attempt_log_path=attempt_log_path,
        )
        return service.generate(request)
