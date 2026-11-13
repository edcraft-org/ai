"""Difficulty, relevance, and finalization tests for the math domain."""

import pytest
from math_helpers import (
    derivative_ir_template,
    ir_add,
    ir_candidate,
    ir_div,
    ir_mul,
    ir_num,
    ir_param,
    ir_sub,
    ir_template,
    quadratic_ir_template,
)

from edcraft_validator.domains.math.candidate_builder import template_sha256
from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Given,
    Goal,
    MathItemSpec,
    ParameterSpec,
    PrimitiveSpec,
    SymbolSpec,
    TextSpec,
    ValidationSpec,
)
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.domains.math.math_types import (
    MATH_DIFFICULTY_TOOL,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
    MATH_TOOL_VERSION,
)
from edcraft_validator.domains.math.relevance import template_relevance_text
from edcraft_validator.mcp.math_tools import assess_template_difficulty
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding
from edcraft_validator.validation.check_names import TEMPLATE_RELEVANCE_CHECK


def small_fraction_template():
    body = MathItemSpec(
        topic="school.fraction_arithmetic",
        symbols=[SymbolSpec(name="amount", kind="given", domain="rational")],
        givens=[
            Given(id="domain_amount", kind="domain", symbol="amount", domain="rational")
        ],
        goal=Goal(kind="evaluate", expr=ir_div(ir_param("half"), ir_num(2))),
        distractors=[
            Distractor(
                value=ir_mul(ir_param("half"), ir_num(2)),
                misconception="MULTIPLIED_INSTEAD",
                reason="Multiplies by two instead of dividing.",
            ),
            Distractor(
                value=ir_add(ir_param("half"), ir_num(2)),
                misconception="ADDED_INSTEAD",
                reason="Adds two instead of dividing.",
            ),
            Distractor(
                value=ir_sub(ir_param("half"), ir_num(2)),
                misconception="SUBTRACTED_INSTEAD",
                reason="Subtracts two instead of dividing.",
            ),
        ],
        text=TextSpec(mode="symbolic", template="Find half of {half} divided by 2."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
    )
    return ir_template(
        "school.fraction_arithmetic",
        [ParameterSpec(name="half", values=["1/2", "1"])],
        body,
    )


def passing_evidence(tool: str) -> ToolEvidence:
    return ToolEvidence(
        tool=tool,
        version=MATH_TOOL_VERSION,
        status="passed",
        details={},
    )


def test_difficulty_bands_follow_the_documented_heuristic() -> None:
    easy = ir_candidate(small_fraction_template(), difficulty="easy")
    medium = ir_candidate(quadratic_ir_template(), difficulty="medium")
    hard = ir_candidate(derivative_ir_template(), difficulty="hard")

    easy_outcome = assess_template_difficulty(easy)
    medium_outcome = assess_template_difficulty(medium)
    hard_outcome = assess_template_difficulty(hard)

    assert easy_outcome.details["estimated_difficulty"] == "easy"
    assert medium_outcome.details["estimated_difficulty"] == "medium"
    assert hard_outcome.details["estimated_difficulty"] == "hard"
    for outcome in (easy_outcome, medium_outcome, hard_outcome):
        assert outcome.details["difficulty_outcome"]["assessment_path"] == "decision"
        assert outcome.details["difficulty_outcome"]["confidence"] is None
        assert outcome.details["difficulty_outcome"]["confidence_source"] is None


def test_relevance_projection_is_learner_facing_only() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    body = candidate.item.body

    text = template_relevance_text(candidate)

    assert "school.quadratic" in text
    assert "Solve {equation}." in text
    assert "p in [2, 3]" in text
    assert candidate.template_id not in text
    assert all(distractor.reason not in text for distractor in body.distractors)


def test_relevance_binding_carries_checked_identity_without_a_candidate() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    request = MathTemplateRequest(
        prompt="Write a quadratic equation question with integer roots.",
        difficulty="easy",
        num_distractors=3,
    )

    bindings = MathDomain().tool_bindings(request, candidate, TEMPLATE_RELEVANCE_CHECK)

    assert bindings == {
        "author_request": request.prompt,
        "question_text": template_relevance_text(candidate),
        "subject_sha256": template_sha256(candidate),
    }
    assert "candidate" not in bindings


def test_finalize_accepts_complete_technical_evidence() -> None:
    candidate = ir_candidate(quadratic_ir_template())

    artifact = MathDomain().finalize_checked_template(
        candidate,
        [
            passing_evidence(MATH_ITEM_SPEC_TOOL),
            passing_evidence(MATH_OPTIONS_TOOL),
        ],
    )

    assert artifact.template == candidate
    assert artifact.validation.combinations_checked == 4
    assert artifact.validation.max_combinations == 4


def test_finalize_keeps_advisory_failures() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    failed_advisory = passing_evidence(MATH_DIFFICULTY_TOOL).model_copy(
        update={
            "status": "failed",
            "findings": [
                ToolFinding(
                    code="DIFFICULTY_MISMATCH",
                    message="Advisory mismatch",
                    field="difficulty",
                )
            ],
            "details": {
                "template_sha256": template_sha256(candidate),
            },
        }
    )

    artifact = MathDomain().finalize_checked_template(
        candidate,
        [
            passing_evidence(MATH_ITEM_SPEC_TOOL),
            passing_evidence(MATH_OPTIONS_TOOL),
            failed_advisory,
        ],
    )

    saved = next(
        item
        for item in artifact.validation.evidence
        if item.check == MATH_DIFFICULTY_TOOL
    )
    assert saved.status == "failed"


def test_finalize_rejects_missing_or_failed_technical_evidence() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    failed_spec = passing_evidence(MATH_ITEM_SPEC_TOOL).model_copy(
        update={
            "status": "failed",
            "findings": [ToolFinding(code="IR_VALIDATION_FAILED", message="Bad item")],
        }
    )

    with pytest.raises(ValueError, match="All selected checks must pass"):
        MathDomain().finalize_checked_template(candidate, [])

    with pytest.raises(ValueError, match="Missing passing option-check"):
        MathDomain().finalize_checked_template(
            candidate, [passing_evidence(MATH_ITEM_SPEC_TOOL)]
        )

    with pytest.raises(ValueError, match="All selected checks must pass"):
        MathDomain().finalize_checked_template(
            candidate,
            [failed_spec, passing_evidence(MATH_OPTIONS_TOOL)],
        )
