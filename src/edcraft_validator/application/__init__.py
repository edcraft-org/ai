"""Application use cases shared by the CLI and future frontends."""

from edcraft_validator.application.evaluate_templates import TemplateEvaluator
from edcraft_validator.application.generate_template import QuestionTemplateApplication

__all__ = ["QuestionTemplateApplication", "TemplateEvaluator"]
