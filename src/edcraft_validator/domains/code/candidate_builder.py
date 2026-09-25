"""Build code template candidates from model-authored proposals."""

from __future__ import annotations

import hashlib
import json

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateProposal,
    CodeTemplateRequest,
)


def build_code_candidate(
    request: CodeTemplateRequest, proposal: CodeTemplateProposal
) -> CodeTemplateCandidate:
    """Build the canonical code template from a model proposal."""
    identity_payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(identity_payload).hexdigest()[:12]
    return CodeTemplateCandidate(
        template_id=f"code.{request.difficulty}.{digest}",
        difficulty=request.difficulty,
        code=proposal.code,
        entry_function=proposal.entry_function,
        parameters=proposal.parameters,
        question_template=proposal.question_template,
        answer_target=proposal.answer_target,
        answer_expression=proposal.answer_expression,
        distractors=proposal.distractors,
        question_type="mcq",
    )
