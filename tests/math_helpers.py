"""Shared valid math-domain fixtures for unit and workflow tests."""

from edcraft_validator.domains.math.candidate_builder import build_math_candidate
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    MathTemplateRequest,
)
from edcraft_validator.domains.math.proposal_response import MathProposalResponse


def math_payload(**overrides):
    payload = {
        "equation_template": "{a}x + {b} = {c}",
        "question_template": "Solve for x: {equation}",
        "parameters": [
            {"name": "a", "values": [2, 3]},
            {"name": "b", "values": [2, 4]},
            {"name": "c", "values": [5, 7]},
        ],
        "answer_expression": "(c - b) / a",
        "distractors": [
            {
                "expression": "(c + b) / a",
                "reason_template": "Adds b instead of subtracting it.",
            },
            {
                "expression": "(c - b) * 2",
                "reason_template": "Multiplies by 2 instead of dividing by a.",
            },
            {
                "expression": "(c - b + 1) / a",
                "reason_template": "Off by one in the numerator.",
            },
        ],
    }
    payload.update(overrides)
    return payload


def math_proposal(**overrides) -> MathProposalResponse:
    return MathProposalResponse.model_validate(math_payload(**overrides))


def math_candidate(
    *,
    difficulty: str = "easy",
    num_distractors: int = 3,
    **overrides,
) -> MathTemplateCandidate:
    request = MathTemplateRequest(
        prompt="Solve a linear equation for x with small integer coefficients.",
        difficulty=difficulty,
        num_distractors=num_distractors,
    )
    return build_math_candidate(request, math_proposal(**overrides))
