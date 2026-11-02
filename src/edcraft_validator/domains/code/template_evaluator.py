"""Compatibility re-exports for code-template evaluation.

The implementation lives in edcraft_validator.application.code_evaluation.
"""

from edcraft_validator.application.code_evaluation import (
    AttemptObserver,
    ProviderFactory,
    TemplateEvaluationAttempt,
    TemplateEvaluationGroup,
    TemplateEvaluationReport,
    TemplateEvaluationSummary,
    TemplateEvaluator,
)

__all__ = [
    "AttemptObserver",
    "ProviderFactory",
    "TemplateEvaluationAttempt",
    "TemplateEvaluationGroup",
    "TemplateEvaluationReport",
    "TemplateEvaluationSummary",
    "TemplateEvaluator",
]
