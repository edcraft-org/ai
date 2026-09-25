"""Domain-agnostic template authoring, validation, and expansion."""

import time
from datetime import UTC, datetime

from pydantic import BaseModel

from edcraft_validator.artifact_contracts import (
    TemplateAuthoringProvenance,
    ValidatedTemplateArtifact,
)
from edcraft_validator.domains.domain_contract import DomainModule
from edcraft_validator.llm.llm_contracts import (
    ModelProvider,
    PlannedGenerationResponse,
)
from edcraft_validator.llm.llm_errors import GenerationSchemaError
from edcraft_validator.validation.check_runner import ValidationPipeline


class TemplateApplication:
    """Run the same template workflow for any registered domain."""

    def __init__(
        self,
        *,
        validator: ValidationPipeline | None = None,
    ) -> None:
        self.validator = validator if validator is not None else ValidationPipeline()

    def create_validated_template(
        self,
        request: BaseModel,
        *,
        domain: DomainModule,
        provider: ModelProvider,
    ) -> ValidatedTemplateArtifact:
        generation_request = domain.generation_request(request)
        generation_started = time.perf_counter()
        response = provider.generate(generation_request)
        generation_duration_ms = (time.perf_counter() - generation_started) * 1000
        if not isinstance(response, PlannedGenerationResponse):
            raise GenerationSchemaError(
                f"{domain.name} generation must return a proposal "
                "and recommended checks"
            )
        self._validate_recommended_checks(
            response, offered_tool_names=generation_request.offered_tool_names
        )
        candidate = domain.build_candidate(request, response.proposal)

        validated = self._validate(domain, candidate, request=request)
        provenance = TemplateAuthoringProvenance(
            provider=provider.provider,
            model=provider.model,
            domain=domain.name,
            base_prompt_version=generation_request.prompt_version,
            request=request.model_dump(mode="json"),
            recommended_checks=response.checks,
            generated_at=datetime.now(UTC),
            generation_duration_ms=generation_duration_ms,
        )
        return validated.model_copy(update={"authoring": provenance})

    @staticmethod
    def _validate_recommended_checks(
        response: PlannedGenerationResponse,
        *,
        offered_tool_names: tuple[str, ...],
    ) -> None:
        offered = set(offered_tool_names)
        unknown = sorted({check.name for check in response.checks} - offered)
        if unknown:
            raise GenerationSchemaError(
                "model recommended checks that were not offered: " + ", ".join(unknown)
            )

    def validate_template(
        self, candidate: BaseModel, *, domain: DomainModule
    ) -> ValidatedTemplateArtifact:
        return self._validate(domain, candidate)

    def _validate[ContextT](
        self,
        domain: DomainModule[ContextT],
        candidate: BaseModel,
        *,
        request: BaseModel | None = None,
    ) -> ValidatedTemplateArtifact:
        plan = domain.prepare_validation(candidate, request=request)
        report = self.validator.validate(
            context=plan.context, checks=plan.checks, policy=plan.policy
        )
        report.raise_for_failure()
        validated = domain.finalize_template(plan.context, report)
        if not isinstance(validated, ValidatedTemplateArtifact):
            raise TypeError(
                f"{domain.name} domain returned a validated artifact "
                "without the shared authoring contract"
            )
        return validated

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, domain: DomainModule, seed: int
    ) -> BaseModel:
        return domain.generate_question(validated, seed=seed)
