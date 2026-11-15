"""Difficulty, relevance, and finalization tests for the math domain."""

import pytest
from math_helpers import (
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

from edcraft_validator.application.difficulty_rubrics import difficulty_rubric
from edcraft_validator.domains.math.candidate_builder import template_sha256
from edcraft_validator.domains.math.difficulty import (
    MATH_DIFFICULTY_RUBRIC_ID,
    MathDifficultyDimensions,
    load_math_difficulty_rubric,
)
from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Given,
    Goal,
    MathItemSpec,
    ParameterSpec,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.domains.math.math_types import (
    MATH_FIDELITY_TOOL,
    MATH_FORM_TOOL,
    MATH_IR_TOOL_VERSION,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
)
from edcraft_validator.domains.math.relevance import template_relevance_text
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding
from edcraft_validator.validation.check_names import (
    TEMPLATE_DIFFICULTY_CHECK,
    TEMPLATE_RELEVANCE_CHECK,
)


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
    )
    return ir_template(
        "school.fraction_arithmetic",
        [ParameterSpec(name="half", values=["1/2", "1"])],
        body,
    )


PROPERTY_DETAILS = {
    "checking_mode": "property_based",
    "examples_checked": 4,
    "execution_calls": 4,
    "max_examples": 4,
    "max_execution_calls": 16,
    "timeout_seconds": 15.0,
    "seed": 0,
    "whole_domain": True,
    "declared_domain_size": 4,
}


def passing_evidence(tool: str) -> ToolEvidence:
    # The item-spec check is the one whose sampled coverage finalisation saves.
    details = dict(PROPERTY_DETAILS) if tool == MATH_ITEM_SPEC_TOOL else {}
    return ToolEvidence(
        tool=tool,
        version=MATH_IR_TOOL_VERSION,
        status="passed",
        details=details,
    )


ADVISORY = frozenset({TEMPLATE_DIFFICULTY_CHECK, TEMPLATE_RELEVANCE_CHECK})


def test_maths_rubric_is_registered_with_four_provisional_dimensions() -> None:
    rubric = load_math_difficulty_rubric()

    assert rubric.rubric_id == MATH_DIFFICULTY_RUBRIC_ID
    assert rubric.version == "math-ir-v0.1"
    assert rubric.assessment_conditions_version == "paper-no-cas-v0.1"
    assert tuple(MathDifficultyDimensions.model_fields) == (
        "procedure_length",
        "operation_type",
        "conceptual_demand",
        "answer_discrimination",
    )
    assert difficulty_rubric(MATH_DIFFICULTY_RUBRIC_ID) == rubric
    for label in MathDifficultyDimensions.model_fields:
        assert f"| {label.replace('_', ' ').capitalize()} |" in rubric.reference
    assert "Number demand" not in rubric.reference
    assert "Representation" not in rubric.reference
    assert "provisional" in rubric.text.lower()
    assert "uncalibrated" in rubric.text.lower()


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
        advisory_checks=ADVISORY,
    )

    assert artifact.template == candidate
    assert artifact.validation.examples_checked == 4
    assert artifact.validation.declared_domain_size == 4


def test_finalize_saves_the_coverage_the_isolated_check_reported() -> None:
    """Finalisation packages evidence; it does not run validation again."""
    candidate = ir_candidate(quadratic_ir_template())
    item_spec = passing_evidence(MATH_ITEM_SPEC_TOOL).model_copy(
        update={
            "details": {
                **PROPERTY_DETAILS,
                "examples_checked": 3,
                "execution_calls": 3,
                "declared_domain_size": 9,
                "seed": 5,
            }
        }
    )

    artifact = MathDomain().finalize_checked_template(
        candidate,
        [item_spec, passing_evidence(MATH_OPTIONS_TOOL)],
        advisory_checks=ADVISORY,
    )

    assert artifact.validation.examples_checked == 3
    assert artifact.validation.declared_domain_size == 9
    assert artifact.validation.seed == 5


def test_finalize_rejects_evidence_without_checked_combinations() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    empty = passing_evidence(MATH_ITEM_SPEC_TOOL).model_copy(
        update={
            "details": {
                **PROPERTY_DETAILS,
                "examples_checked": 0,
                "execution_calls": 0,
            }
        }
    )

    with pytest.raises(ValueError, match="checked no parameter combinations"):
        MathDomain().finalize_checked_template(
            candidate,
            [empty, passing_evidence(MATH_OPTIONS_TOOL)],
            advisory_checks=ADVISORY,
        )


def test_required_checks_follow_the_candidate() -> None:
    domain = MathDomain()
    solve = ir_candidate(quadratic_ir_template())
    assert domain.required_checks(solve) == {MATH_ITEM_SPEC_TOOL, MATH_OPTIONS_TOOL}

    body = solve.item.body
    prose = solve.model_copy(
        update={
            "item": solve.item.model_copy(
                update={
                    "body": body.model_copy(
                        update={"text": body.text.model_copy(update={"mode": "prose"})}
                    )
                }
            )
        }
    )
    assert MATH_FIDELITY_TOOL in domain.required_checks(prose)

    factor = solve.model_copy(
        update={
            "item": solve.item.model_copy(
                update={
                    "body": body.model_copy(
                        update={"goal": body.goal.model_copy(update={"kind": "factor"})}
                    )
                }
            )
        }
    )
    assert MATH_FORM_TOOL in domain.required_checks(factor)


def test_finalize_keeps_advisory_failures() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    failed_advisory = passing_evidence(TEMPLATE_DIFFICULTY_CHECK).model_copy(
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
        advisory_checks=ADVISORY,
    )

    saved = next(
        item
        for item in artifact.validation.evidence
        if item.check == TEMPLATE_DIFFICULTY_CHECK
    )
    assert saved.status == "failed"
    assert saved.details["advisory"] is True


def test_finalize_rejects_missing_or_failed_technical_evidence() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    failed_spec = passing_evidence(MATH_ITEM_SPEC_TOOL).model_copy(
        update={
            "status": "failed",
            "findings": [ToolFinding(code="IR_VALIDATION_FAILED", message="Bad item")],
        }
    )

    with pytest.raises(ValueError, match="All selected checks must pass"):
        MathDomain().finalize_checked_template(candidate, [], advisory_checks=ADVISORY)

    with pytest.raises(ValueError, match="Missing passing required checks"):
        MathDomain().finalize_checked_template(
            candidate,
            [passing_evidence(MATH_ITEM_SPEC_TOOL)],
            advisory_checks=ADVISORY,
        )

    with pytest.raises(ValueError, match="All selected checks must pass"):
        MathDomain().finalize_checked_template(
            candidate,
            [failed_spec, passing_evidence(MATH_OPTIONS_TOOL)],
            advisory_checks=ADVISORY,
        )
