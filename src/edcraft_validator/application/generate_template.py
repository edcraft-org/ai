"""Application use cases for authoring and expanding question templates."""

from __future__ import annotations

import time
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
from edcraft_validator.generation.models import (
    TemplateAuthoringProvenance,
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
        generator = self.generator_factory(selection)
        prompt = generator.prompt_metadata(request)
        generation_started = time.perf_counter()
        proposal = generator.generate_proposal(request)
        generation_duration_ms = (time.perf_counter() - generation_started) * 1000
        template = normalize_code_template_proposal(request, proposal)
        validation_started = time.perf_counter()
        approved = self.validator_factory().validate(
            template, num_distractors=request.num_distractors
        )
        validation_duration_ms = (time.perf_counter() - validation_started) * 1000
        authoring = TemplateAuthoringProvenance(
            provider=generator.provider,
            model=generator.model,
            prompt=prompt,
            request=request,
            generation_duration_ms=generation_duration_ms,
            validation_duration_ms=validation_duration_ms,
        )
        return approved.model_copy(update={"authoring": authoring})

    def approve(self, template: CodeQuestionTemplate) -> ApprovedCodeQuestionTemplate:
        return self.validator_factory().validate(template)

    def generate(
        self, approved: ApprovedCodeQuestionTemplate, *, seed: int
    ) -> TemplateQuestionInstance:
        return self.instance_generator.generate(approved, seed=seed)
