"""Backward-compatible import name for the math proposal response schema.

The response model is the same Pydantic model as the authored template content;
the separate subclass only existed to give the LLM schema a stable name. Keep
the alias so downstream packages that import it keep working.
"""

from edcraft_validator.domains.math.math_schemas import MathTemplateContent

MathProposalResponse = MathTemplateContent

__all__ = ["MathProposalResponse"]
