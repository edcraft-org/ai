"""Typed LLM response schema for math template proposals."""

from edcraft_validator.domains.math.math_schemas import MathTemplateContent


class MathProposalResponse(MathTemplateContent):
    """Provider-independent typed response schema for a math proposal."""
