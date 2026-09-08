"""Code-domain implementation of the generic domain contract."""

from collections.abc import Callable

from pydantic import BaseModel

from edcraft_validator.domains.code.authoring import build_code_generation_request
from edcraft_validator.domains.code.models import CodeTemplateAuthoringRequest
from edcraft_validator.domains.code.templates import (
    ApprovedCodeQuestionTemplate,
    CodeQuestionTemplate,
    CodeTemplateProposal,
    TemplateQuestionInstance,
    TemplateValidator,
    build_code_template,
    generate_template_instance,
)
from edcraft_validator.generation.base import StructuredGenerationRequest

ValidatorFactory = Callable[[], TemplateValidator]
InstanceGenerator = Callable[
    [ApprovedCodeQuestionTemplate, int], TemplateQuestionInstance
]


class CodeDomain:
    """Prompting, validation, and expansion for code templates."""

    name = "code"
    request_model = CodeTemplateAuthoringRequest
    template_model = CodeQuestionTemplate
    approved_model = ApprovedCodeQuestionTemplate

    def __init__(
        self,
        *,
        validator_factory: ValidatorFactory = TemplateValidator,
        instance_generator: InstanceGenerator = generate_template_instance,
    ) -> None:
        self.validator_factory = validator_factory
        self.instance_generator = instance_generator

    def generation_request(
        self, request: BaseModel, *, provider: str
    ) -> StructuredGenerationRequest[CodeTemplateProposal]:
        typed_request = _require_type(request, CodeTemplateAuthoringRequest)
        return build_code_generation_request(typed_request, provider=provider)

    def build_template(
        self, request: BaseModel, proposal: BaseModel
    ) -> CodeQuestionTemplate:
        return build_code_template(
            _require_type(request, CodeTemplateAuthoringRequest),
            _require_type(proposal, CodeTemplateProposal),
        )

    def approve(
        self, template: BaseModel, *, request: BaseModel | None = None
    ) -> ApprovedCodeQuestionTemplate:
        typed_template = _require_type(template, CodeQuestionTemplate)
        num_distractors = None
        if request is not None:
            num_distractors = _require_type(
                request, CodeTemplateAuthoringRequest
            ).num_distractors
        return self.validator_factory().validate(
            typed_template, num_distractors=num_distractors
        )

    def generate(self, approved: BaseModel, *, seed: int) -> TemplateQuestionInstance:
        return self.instance_generator(
            _require_type(approved, ApprovedCodeQuestionTemplate), seed
        )


def _require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    if not isinstance(value, model):
        raise TypeError(f"code domain requires {model.__name__}")
    return value
