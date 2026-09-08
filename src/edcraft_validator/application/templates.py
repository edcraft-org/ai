"""Domain-agnostic template authoring, approval, and expansion."""

import time
from collections.abc import Callable

from pydantic import BaseModel

from edcraft_validator.domains.base import DomainModule
from edcraft_validator.domains.registry import create_domain
from edcraft_validator.generation.base import ModelProvider
from edcraft_validator.generation.models import (
    TemplateAuthoringProvenance,
    TemplateProviderSelection,
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

    def author(
        self,
        request: BaseModel,
        *,
        domain: str,
        provider: str,
        model: str | None = None,
    ) -> BaseModel:
        domain_module = self.domain_factory(domain)
        model_provider = self.provider_factory(
            TemplateProviderSelection(provider=provider, model=model)
        )
        generation_request = domain_module.generation_request(
            request, provider=model_provider.provider
        )
        prompt = generation_request.prompt_metadata()

        generation_started = time.perf_counter()
        proposal = model_provider.generate(generation_request)
        generation_duration_ms = (time.perf_counter() - generation_started) * 1000
        template = domain_module.build_template(request, proposal)

        validation_started = time.perf_counter()
        approved = domain_module.approve(template, request=request)
        validation_duration_ms = (time.perf_counter() - validation_started) * 1000
        provenance = TemplateAuthoringProvenance(
            provider=model_provider.provider,
            model=model_provider.model,
            domain=domain_module.name,
            prompt=prompt,
            request=request.model_dump(mode="json"),
            generation_duration_ms=generation_duration_ms,
            validation_duration_ms=validation_duration_ms,
        )
        return approved.model_copy(update={"authoring": provenance})

    def approve(self, template: BaseModel, *, domain: str) -> BaseModel:
        return self.domain_factory(domain).approve(template)

    def generate(self, approved: BaseModel, *, domain: str, seed: int) -> BaseModel:
        return self.domain_factory(domain).generate(approved, seed=seed)
