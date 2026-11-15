"""Build math template candidates from model-authored proposals.

The candidate keeps the generic item, trims distractors beyond the requested
number and derives a content identifier. Every saved distractor then appears in
each generated question.
"""

from __future__ import annotations

from edcraft_validator.domains.domain_support import (
    build_template_id,
    content_sha256,
)
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
)


def build_math_candidate(
    request: MathTemplateRequest, proposal: MathTemplateContent
) -> MathTemplateCandidate:
    """Build the canonical math template from the generic IR proposal.

    Every saved distractor appears in every generated question, so extra
    distractors beyond the requested number are dropped here. Too few is left
    for the application to report.
    """
    item = proposal.item
    if item is not None and len(item.body.distractors) > request.num_distractors:
        kept = item.body.distractors[: request.num_distractors]
        item = item.model_copy(
            update={"body": item.body.model_copy(update={"distractors": kept})}
        )

    return MathTemplateCandidate(
        template_id=build_template_id("math", request, proposal),
        difficulty=request.difficulty,
        item=item,
        question_type="mcq",
    )


def template_sha256(candidate: MathTemplateCandidate) -> str:
    """Identify the exact reusable content independently of any assessment."""
    return content_sha256(candidate)
