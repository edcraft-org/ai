"""Application use cases shared by the CLI and future frontends."""

from edcraft_validator.application.generate_question import (
    QuestionGenerationApplication,
)
from edcraft_validator.application.generate_template import QuestionTemplateApplication

__all__ = ["QuestionGenerationApplication", "QuestionTemplateApplication"]
