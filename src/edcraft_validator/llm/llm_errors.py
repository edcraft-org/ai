"""Failures at the LLM transport and response boundary."""

from __future__ import annotations


class GenerationError(RuntimeError):
    """Raised when a provider cannot produce a usable structured result."""

    category = "generation_error"


class GenerationTimeoutError(GenerationError):
    category = "timeout"


class GenerationTransportError(GenerationError):
    category = "transport"


class GenerationResponseError(GenerationError):
    category = "invalid_response"


class GenerationSchemaError(GenerationError):
    category = "schema_validation"
