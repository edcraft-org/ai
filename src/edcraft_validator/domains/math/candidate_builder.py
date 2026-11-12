"""Build math template candidates from model-authored proposals."""

from __future__ import annotations

import hashlib
import json

from edcraft_validator.domains.domain_support import content_sha256
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
)


def build_math_candidate(
    request: MathTemplateRequest, proposal: MathTemplateContent
) -> MathTemplateCandidate:
    """Build the canonical math template from either authoring mode."""
    identity_payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(identity_payload).hexdigest()[:12]
    template_id = f"math.{request.difficulty}.{digest}"
    if proposal.item is not None:
        return MathTemplateCandidate(
            template_id=template_id,
            difficulty=request.difficulty,
            item=proposal.item,
            question_type="mcq",
        )
    return MathTemplateCandidate(
        template_id=template_id,
        difficulty=request.difficulty,
        equation_template=proposal.equation_template,
        question_template=proposal.question_template,
        parameters=proposal.parameters,
        answer_expression=proposal.answer_expression,
        distractors=proposal.distractors,
        question_type="mcq",
    )


def template_sha256(candidate: MathTemplateCandidate) -> str:
    """Identify the exact reusable content independently of any assessment."""
    return content_sha256(candidate)
