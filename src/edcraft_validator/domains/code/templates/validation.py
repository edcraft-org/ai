"""Validation plan and finalization for finite code-question templates."""

from __future__ import annotations

from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)
from edcraft_validator.validation.contracts import (
    ValidationPlan,
    ValidationPolicy,
    ValidationReport,
)

from .answers import (
    check_canonical_answers,
    check_expressions,
    check_proposed_answers,
)
from .checks import CodeCheck
from .context import CodeValidationContext
from .distractors import check_distractors, check_selection, selected_count
from .execution import ExecutionCheck
from .models import (
    CodeTemplateCandidate,
    TemplateValidationSummary,
    ValidatedCodeTemplate,
    ValidatedTemplateCase,
)
from .structure import check_rendering, check_structure

CODE_TEMPLATE_VALIDATOR_VERSION = "code-template-validator-v3"


class TemplateValidator:
    """Build code-domain checks and package their validated results."""

    def __init__(
        self,
        *,
        execution_tool: PythonExecutionTool | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.execution_check = ExecutionCheck(
            execution_tool=execution_tool or LocalPythonTool(),
            timeout_seconds=timeout_seconds,
        )

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

    def prepare_validation(
        self, template: CodeTemplateCandidate, *, num_distractors: int | None = None
    ) -> ValidationPlan[CodeValidationContext]:
        checks = self.build_checks()
        # Manual candidates only need selection when execution corrects their answer.
        # Consistency is always required, even when selection is inapplicable.
        required = frozenset(
            {
                "template_structure",
                "expression_safety",
                "answer_domain",
                "code_execution",
                "canonical_answers",
                "distractor_consistency",
                "template_rendering",
            }
        )
        if num_distractors is not None:
            required |= {"distractor_selection"}
        return ValidationPlan(
            context=CodeValidationContext(template, num_distractors=num_distractors),
            checks=checks,
            policy=ValidationPolicy(required_checks=required),
        )

    def build_checks(self) -> tuple[CodeCheck, ...]:
        """Keep prerequisites explicit; every operation uses the same typed context."""
        return (
            CodeCheck(
                "template_structure",
                "bounded",
                check_structure,
                lambda ctx: {
                    "topic": ctx.template.topic,
                    "difficulty": ctx.template.difficulty,
                },
            ),
            CodeCheck(
                "expression_safety",
                "bounded",
                check_expressions,
                lambda ctx: {"distractors": len(ctx.template.distractors)},
            ),
            CodeCheck(
                "answer_domain",
                "exhaustive",
                check_proposed_answers,
                lambda ctx: ctx.case_details,
            ),
            CodeCheck(
                "code_execution",
                "exhaustive",
                self.execution_check.run,
                lambda ctx: {
                    **ctx.case_details,
                    "tool": type(self.execution_check.execution_tool).__name__,
                },
            ),
            CodeCheck(
                "canonical_answers",
                "exhaustive",
                check_canonical_answers,
                lambda ctx: {**ctx.case_details, "source": "code_execution"},
            ),
            CodeCheck(
                "distractor_selection",
                "exhaustive",
                check_selection,
                lambda ctx: {
                    **ctx.case_details,
                    "selected": selected_count(ctx),
                },
            ),
            CodeCheck(
                "distractor_consistency",
                "exhaustive",
                check_distractors,
                lambda ctx: {
                    **ctx.case_details,
                    "distractors": len(ctx.candidates),
                },
            ),
            CodeCheck(
                "template_rendering",
                "exhaustive",
                check_rendering,
                lambda ctx: ctx.case_details,
            ),
        )
