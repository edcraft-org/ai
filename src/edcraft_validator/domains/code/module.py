"""Code-domain implementation of the generic domain contract."""

from collections.abc import Callable

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
from edcraft_validator.generation.base import StructuredGenerationRequest

ValidatorFactory = Callable[[], TemplateValidator]
InstanceGenerator = Callable[[ValidatedCodeTemplate, int], CodeQuestionInstance]


class CodeDomain:
    """Prompting, validation, and expansion for code templates."""

    name = "code"
    request_model = CodeTemplateRequest
    candidate_model = CodeTemplateCandidate
    validated_model = ValidatedCodeTemplate

    def __init__(
        self,
        *,
        validator_factory: ValidatorFactory = TemplateValidator,
        instance_generator: InstanceGenerator = generate_code_question,
    ) -> None:
        self.validator_factory = validator_factory
        self.instance_generator = instance_generator

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

    def validate(
        self, candidate: BaseModel, *, request: BaseModel | None = None
    ) -> ValidatedCodeTemplate:
        typed_candidate = _require_type(candidate, CodeTemplateCandidate)
        num_distractors = None
        if request is not None:
            num_distractors = _require_type(
                request, CodeTemplateRequest
            ).num_distractors
        return self.validator_factory().validate(
            typed_candidate, num_distractors=num_distractors
        )

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> CodeQuestionInstance:
        return self.instance_generator(
            _require_type(validated, ValidatedCodeTemplate), seed
        )


def _require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    if not isinstance(value, model):
        raise TypeError(f"code domain requires {model.__name__}")
    return value
