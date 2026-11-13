"""Learner-facing text projection for shared template relevance.

The measurement, threshold and verdict live in the shared classifier. This
module only renders what a learner would actually see, so the same relevance
policy can judge a math template without knowing anything about equations.
"""

from __future__ import annotations

from edcraft_validator.domains.math.math_schemas import MathTemplateCandidate


def template_relevance_text(candidate: MathTemplateCandidate) -> str:
    """Render the reusable task without answers, hints or distractor recipes."""
    template = candidate.item
    if template is None:
        raise ValueError("relevance text requires a generic item template")
    parameters = "; ".join(
        f"{parameter.name} in [{', '.join(parameter.values)}]"
        for parameter in template.parameters
    )
    return (
        "Mathematics multiple-choice question template\n\n"
        f"Topic: {template.topic}\n"
        f"Task: {template.body.text.template}\n"
        f"Goal: {template.body.goal.kind}\n"
        f"Parameter values: {parameters}\n"
        "Each generated question substitutes one allowed value for every "
        "parameter.\n"
    )
