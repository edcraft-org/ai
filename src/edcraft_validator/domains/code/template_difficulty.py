"""Code-domain template projection for the shared difficulty cascade.

The shared cascade owns request building, judging and evidence. This module keeps
only the code-specific scope text and the blinded payload the judge receives.
"""

import json

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.difficulty import (
    REASONING_PROCEDURE,
    TEMPLATE_SCOPE,
)

__all__ = [
    "REASONING_PROCEDURE",
    "TEMPLATE_SCOPE",
    "blinded_template_payload",
]


def blinded_template_payload(candidate: CodeTemplateCandidate) -> str:
    return json.dumps(
        {
            "template": candidate.model_dump(
                mode="json", exclude={"template_id", "topic", "difficulty"}
            )
        }
    )
