"""Application use cases for authoring and expanding question templates."""

from __future__ import annotations

from collections.abc import Callable

from edcraft_validator.domains.code.templates import (
    ApprovedCodeQuestionTemplate,
    CodeQuestionTemplate,
    TemplateInstanceGenerator,
    TemplateQuestionInstance,
    TemplateValidator,
    normalize_code_template_proposal,
)
from edcraft_validator.generation.base import QuestionTemplateGenerator
from edcraft_validator.generation.models import TemplateAuthoringRequest
from edcraft_validator.generation.registry import create_template_generator

TemplateGeneratorFactory = Callable[[str], QuestionTemplateGenerator]
TemplateValidatorFactory = Callable[[], TemplateValidator]


class QuestionTemplateApplication:
    """Author once with AI, approve exhaustively, then expand locally."""

    def __init__(
        self,
        *,
        generator_factory: TemplateGeneratorFactory = create_template_generator,
        validator_factory: TemplateValidatorFactory = TemplateValidator,
        instance_generator: TemplateInstanceGenerator | None = None,
    ) -> None:
        self.generator_factory = generator_factory
        self.validator_factory = validator_factory
        self.instance_generator = instance_generator or TemplateInstanceGenerator()

    def author(
        self, request: TemplateAuthoringRequest, *, provider: str
    ) -> ApprovedCodeQuestionTemplate:
        proposal = self.generator_factory(provider).generate_proposal(request)
        template = normalize_code_template_proposal(request, proposal)
        return self.validator_factory().validate(
            template, num_distractors=request.num_distractors
        )

    def approve(self, template: CodeQuestionTemplate) -> ApprovedCodeQuestionTemplate:
        return self.validator_factory().validate(template)

    def generate(
        self, approved: ApprovedCodeQuestionTemplate, *, seed: int
    ) -> TemplateQuestionInstance:
        return self.instance_generator.generate(approved, seed=seed)
