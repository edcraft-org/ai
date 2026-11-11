"""Learner-facing text projection for shared template relevance.

The measurement, threshold and verdict live in the shared classifier. This
module only renders what a learner would actually see, so the same relevance
policy can judge a math template without knowing anything about equations.
"""

from __future__ import annotations

from edcraft_validator.domains.math.math_schemas import MathTemplateCandidate


def template_relevance_text(candidate: MathTemplateCandidate) -> str:
    """Render the reusable task without answers, hints or distractor recipes."""
    parameters = ", ".join(
        f"{parameter.name} in {parameter.values}" for parameter in candidate.parameters
    )
    return (
        "Mathematics multiple-choice question template\n\n"
        f"Equation: {candidate.equation_template}\n"
        f"Question: {candidate.question_template}\n"
        f"Parameter values: {parameters}\n"
        "Each generated question substitutes one allowed value for every "
        "placeholder.\n"
    )
