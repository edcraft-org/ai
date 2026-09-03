"""Application use cases shared by the CLI and future frontends."""

from edcraft_validator.domains.code.application import QuestionTemplateApplication
from edcraft_validator.domains.code.evaluation import TemplateEvaluator

__all__ = ["QuestionTemplateApplication", "TemplateEvaluator"]
