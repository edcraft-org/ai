"""Validation plan and finalization for finite code-question templates."""

from __future__ import annotations

from edcraft_validator.validation.contracts import (
    ValidationReport,
)

from .context import CodeValidationContext
from .models import (
    TemplateValidationSummary,
    ValidatedCodeTemplate,
    ValidatedTemplateCase,
)

CODE_TEMPLATE_VALIDATOR_VERSION = "code-template-validator-v3"


class TemplateValidator:
    """Build code-domain checks and package their validated results."""

    @staticmethod
    def finalize_template(
        context: CodeValidationContext, report: ValidationReport
    ) -> ValidatedCodeTemplate:
        """Package checked values only; no generation or tool calls happen here."""
        report.raise_for_failure()
        cases = [
            ValidatedTemplateCase(inputs=inputs, answer=answer)
            for inputs, answer in zip(
                context.inputs_cases, context.canonical_answers, strict=True
            )
        ]
        return ValidatedCodeTemplate(
            template=context.template.model_copy(
                update={"answer_expression": None}, deep=True
            ),
            validation=TemplateValidationSummary(
                validator_version=CODE_TEMPLATE_VALIDATOR_VERSION,
                cases_validated=len(cases),
                validated_cases=cases,
                evidence=report.evidence,
            ),
        )
