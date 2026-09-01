"""Backward-compatible imports for the code-domain generation contract.

New code should import these models and helpers from
``edcraft_validator.domains.code.generation``.
"""

from edcraft_validator.domains.code.generation import (
    JsonScalar,
    QuestionDraftResponse,
    TaggedInput,
    TaggedJsonObjectEntry,
    TaggedJsonValue,
    build_prompt,
    normalize_plain_response,
)

__all__ = [
    "JsonScalar",
    "QuestionDraftResponse",
    "TaggedInput",
    "TaggedJsonObjectEntry",
    "TaggedJsonValue",
    "build_prompt",
    "normalize_plain_response",
]
