"""Application use cases for authoring and expanding question templates."""

from __future__ import annotations

from collections.abc import Callable

from edcraft_validator.domains.code.templates import (
    ApprovedCodeQuestionTemplate,
    CodeQuestionTemplate,
    TemplateInstanceGenerator,
    TemplateQuestionInstance,
    TemplateValidationError,
    TemplateValidator,
    answer_target_for_topic,
)
from edcraft_validator.generation.base import QuestionTemplateGenerator
from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplateProviderSelection,
)
from edcraft_validator.generation.registry import create_template_generator

TemplateGeneratorFactory = Callable[
    [TemplateProviderSelection], QuestionTemplateGenerator
]
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
        self,
        request: TemplateAuthoringRequest,
        *,
        provider: str,
        model: str | None = None,
    ) -> ApprovedCodeQuestionTemplate:
        selection = TemplateProviderSelection(provider=provider, model=model)
        template = self.generator_factory(selection).generate_template(request)
        if template.topic != request.topic:
            raise TemplateValidationError(
                f"template topic {template.topic!r} does not match {request.topic!r}"
            )
        if template.difficulty != request.difficulty:
            raise TemplateValidationError(
                "template difficulty does not match the authoring request"
            )
        expected_target = answer_target_for_topic(request.topic)
        if template.answer_target != expected_target:
            raise TemplateValidationError(
                f"template answer_target {template.answer_target!r} does not match "
                f"the {request.topic!r} topic target {expected_target!r}"
            )
        if len(template.distractors) != request.num_distractors:
            raise TemplateValidationError(
                f"expected {request.num_distractors} distractor recipes, received "
                f"{len(template.distractors)}"
            )
        return self.approve(template)

    def approve(self, template: CodeQuestionTemplate) -> ApprovedCodeQuestionTemplate:
        return self.validator_factory().validate(template)

    def generate(
        self, approved: ApprovedCodeQuestionTemplate, *, seed: int
    ) -> TemplateQuestionInstance:
        return self.instance_generator.generate(approved, seed=seed)
