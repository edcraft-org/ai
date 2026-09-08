"""Contract implemented by every EdCraft question domain."""

from typing import Protocol

from pydantic import BaseModel

from edcraft_validator.generation.base import StructuredGenerationRequest


class DomainModule(Protocol):
    """Domain-specific behavior used by the generic application workflow."""

    name: str
    request_model: type[BaseModel]
    template_model: type[BaseModel]
    approved_model: type[BaseModel]

    def generation_request(
        self, request: BaseModel, *, provider: str
    ) -> StructuredGenerationRequest: ...

    def build_template(self, request: BaseModel, proposal: BaseModel) -> BaseModel: ...

    def approve(
        self, template: BaseModel, *, request: BaseModel | None = None
    ) -> BaseModel: ...

    def generate(self, approved: BaseModel, *, seed: int) -> BaseModel: ...
