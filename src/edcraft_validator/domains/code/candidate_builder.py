"""Build code template candidates from model-authored proposals."""

from __future__ import annotations

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateContent,
    CodeTemplateRequest,
)
from edcraft_validator.domains.domain_support import (
    build_template_id,
    content_sha256,
)


def build_code_candidate(
    request: CodeTemplateRequest, proposal: CodeTemplateContent
) -> CodeTemplateCandidate:
    """Build the canonical code template from a model proposal."""
    return CodeTemplateCandidate(
        template_id=build_template_id("code", request, proposal),
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


def template_sha256(candidate: CodeTemplateCandidate) -> str:
    """Identify the exact reusable content independently of any assessment."""
    return content_sha256(candidate)
