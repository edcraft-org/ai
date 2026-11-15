"""Provisional math-template difficulty estimate from a deterministic heuristic."""

import time
from fractions import Fraction

from edcraft_validator.application.authoring_contracts import DifficultyOutcome
from edcraft_validator.domains.math.candidate_builder import template_sha256
from edcraft_validator.domains.math.ir.instantiate import declared_domain_size
from edcraft_validator.domains.math.math_schemas import MathTemplateCandidate
from edcraft_validator.domains.math.math_types import (
    MATH_DIFFICULTY_TOOL,
    MATH_TOOL_VERSION,
    Difficulty,
)
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding


def assess_template_difficulty(candidate: MathTemplateCandidate) -> ToolEvidence:
    """Return a deterministic provisional difficulty estimate."""
    started = time.perf_counter()
    estimate = _estimate_difficulty(candidate)
    matches = estimate == candidate.difficulty
    outcome = DifficultyOutcome(
        # This is a deterministic policy rule, not model reasoning and not a
        # calibrated confidence. Reporting either would misstate the evidence.
        assessment_path="decision",
        requested_difficulty=candidate.difficulty,
        estimated_difficulty=estimate,
        decision="matches" if matches else "advisory_mismatch",
        status="passed" if matches else "failed",
        reason=(
            "Provisional deterministic heuristic from parameter magnitude, sign "
            "variety, parameter-domain size, and distractor count; not calibrated."
        ),
    )
    findings = (
        []
        if matches
        else [
            ToolFinding(
                code="DIFFICULTY_MISMATCH",
                message=(
                    f"Heuristic estimate is {estimate}; requested "
                    f"{candidate.difficulty}. Advisory only."
                ),
                field="difficulty",
            )
        ]
    )
    details = {
        "advisory": True,
        "provisional": True,
        "calibrated": False,
        "subject_sha256": template_sha256(candidate),
        "requested_difficulty": candidate.difficulty,
        "difficulty_outcome": outcome.model_dump(mode="json"),
        **outcome.model_dump(
            mode="json",
            include={
                "assessment_path",
                "requested_difficulty",
                "estimated_difficulty",
                "confidence",
                "confidence_source",
                "decision",
            },
        ),
    }
    return ToolEvidence(
        tool=MATH_DIFFICULTY_TOOL,
        version=MATH_TOOL_VERSION,
        status=outcome.status,
        findings=findings,
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def _estimate_difficulty(candidate: MathTemplateCandidate) -> Difficulty:
    template = candidate.item
    if template is None:
        raise ValueError("difficulty estimation requires a generic item template")
    values = [
        abs(Fraction(value))
        for parameter in template.parameters
        for value in parameter.values
    ]
    score = 0
    if len(template.parameters) >= 2:
        score += 1
    if any(value > 1 for value in values):
        score += 1
    if any(
        Fraction(value) < 0
        for parameter in template.parameters
        for value in parameter.values
    ):
        score += 1
    if declared_domain_size(template) >= 60:
        score += 1
    if len(template.body.distractors) >= 4:
        score += 1
    if template.topic.startswith("university."):
        score += 1
    if score <= 1:
        return "easy"
    if score <= 3:
        return "medium"
    return "hard"


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
