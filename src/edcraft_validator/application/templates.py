"""Domain-agnostic template authoring, validation, and expansion."""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from edcraft_validator.domains.base import DomainModule
from edcraft_validator.domains.registry import create_domain
from edcraft_validator.generation.base import ModelProvider
from edcraft_validator.generation.models import (
    TemplateAuthoringProvenance,
    TemplateProviderSelection,
    ValidatedTemplateArtifact,
)
from edcraft_validator.generation.registry import create_model_provider

ProviderFactory = Callable[[TemplateProviderSelection], ModelProvider]
DomainFactory = Callable[[str], DomainModule]


class TemplateApplication:
    """Run the same template workflow for any registered domain."""

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory = create_model_provider,
        domain_factory: DomainFactory = create_domain,
    ) -> None:
        self.provider_factory = provider_factory
        self.domain_factory = domain_factory

    def create_validated_template(
        self,
        request: BaseModel,
        *,
        domain: str,
        provider: str,
        model: str | None = None,
    ) -> ValidatedTemplateArtifact:
        domain_module = self.domain_factory(domain)
        model_provider = self.provider_factory(
            TemplateProviderSelection(provider=provider, model=model)
        )
        generation_request = domain_module.generation_request(
            request, provider=model_provider.provider
        )
        generation_started = time.perf_counter()
        proposal = model_provider.generate(generation_request)
        generation_duration_ms = (time.perf_counter() - generation_started) * 1000
        candidate = domain_module.build_candidate(request, proposal)

        validated = domain_module.validate(candidate, request=request)
        if not isinstance(validated, ValidatedTemplateArtifact):
            raise TypeError(
                f"{domain_module.name} domain returned a validated artifact "
                "without the shared authoring contract"
            )
        provenance = TemplateAuthoringProvenance(
            provider=model_provider.provider,
            model=model_provider.model,
            domain=domain_module.name,
            base_prompt_version=generation_request.prompt_version,
            request=request.model_dump(mode="json"),
            generated_at=datetime.now(UTC),
            generation_duration_ms=generation_duration_ms,
        )
        return validated.model_copy(update={"authoring": provenance})

    def validate_template(
        self, candidate: BaseModel, *, domain: str
    ) -> ValidatedTemplateArtifact:
        domain_module = self.domain_factory(domain)
        validated = domain_module.validate(candidate)
        if not isinstance(validated, ValidatedTemplateArtifact):
            raise TypeError(
                f"{domain_module.name} domain returned a validated artifact "
                "without the shared authoring contract"
            )
        return validated

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, domain: str, seed: int
    ) -> BaseModel:
        return self.domain_factory(domain).generate_question(validated, seed=seed)
