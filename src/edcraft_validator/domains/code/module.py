"""Code-domain implementation of the generic domain contract."""

from pydantic import BaseModel

from edcraft_validator.domains.code.authoring import build_code_generation_request
from edcraft_validator.domains.code.models import CodeTemplateRequest
from edcraft_validator.domains.code.templates import (
    CodeQuestionInstance,
    CodeTemplateCandidate,
    CodeTemplateProposal,
    TemplateValidator,
    ValidatedCodeTemplate,
    build_code_candidate,
    generate_code_question,
)
from edcraft_validator.domains.code.templates.answers import (
    check_canonical_answers,
    check_expressions,
    check_proposed_answers,
)
from edcraft_validator.domains.code.templates.checks import CodeCheck
from edcraft_validator.domains.code.templates.context import CodeValidationContext
from edcraft_validator.domains.code.templates.distractors import (
    check_distractors,
    check_selection,
    selected_count,
)
from edcraft_validator.domains.code.templates.execution import ExecutionCheck
from edcraft_validator.domains.code.templates.structure import (
    check_rendering,
    check_structure,
)
from edcraft_validator.generation.base import StructuredGenerationRequest
from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)
from edcraft_validator.validation.contracts import (
    ValidationPlan,
    ValidationPolicy,
    ValidationReport,
)


class CodeDomain:
    """Prompting, validation, and expansion for code templates."""

    name = "code"
    request_model = CodeTemplateRequest
    candidate_model = CodeTemplateCandidate
    validated_model = ValidatedCodeTemplate

    def __init__(
        self,
        *,
        execution_tool: PythonExecutionTool | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.execution_tool = (
            execution_tool if execution_tool is not None else LocalPythonTool()
        )
        self.timeout_seconds = timeout_seconds

    def generation_request(
        self, request: BaseModel, *, provider: str
    ) -> StructuredGenerationRequest[CodeTemplateProposal]:
        typed_request = _require_type(request, CodeTemplateRequest)
        return build_code_generation_request(typed_request, provider=provider)

    def build_candidate(
        self, request: BaseModel, proposal: BaseModel
    ) -> CodeTemplateCandidate:
        return build_code_candidate(
            _require_type(request, CodeTemplateRequest),
            _require_type(proposal, CodeTemplateProposal),
        )

    def prepare_validation(
        self, candidate: BaseModel, *, request: BaseModel | None = None
    ) -> ValidationPlan[CodeValidationContext]:
        typed_candidate = _require_type(candidate, CodeTemplateCandidate)
        num_distractors = None
        if request is not None:
            num_distractors = _require_type(
                request, CodeTemplateRequest
            ).num_distractors
        execution_check = ExecutionCheck(self.execution_tool, self.timeout_seconds)
        checks = (
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
                execution_check.run,
                lambda ctx: {
                    **ctx.case_details,
                    "tool": type(execution_check.execution_tool).__name__,
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
            context=CodeValidationContext(
                typed_candidate, num_distractors=num_distractors
            ),
            checks=checks,
            policy=ValidationPolicy(required_checks=required),
        )

    def finalize_template(
        self, context: CodeValidationContext, report: ValidationReport
    ) -> ValidatedCodeTemplate:
        return TemplateValidator.finalize_template(context, report)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> CodeQuestionInstance:
        return generate_code_question(
            _require_type(validated, ValidatedCodeTemplate), seed
        )


def _require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    if not isinstance(value, model):
        raise TypeError(f"code domain requires {model.__name__}")
    return value
