"""Exact answer, distractor, and finalization tests for the math domain."""

import copy

import pytest
from math_helpers import math_candidate, math_payload

from edcraft_validator.domains.math.candidate_builder import template_sha256
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_types import (
    MATH_ANSWERS_TOOL,
    MATH_DIFFICULTY_TOOL,
    MATH_STRUCTURE_TOOL,
    MATH_TOOL_VERSION,
)
from edcraft_validator.mcp.math_tools import (
    MathToolFailure,
    assess_template_difficulty,
    assess_template_relevance,
    validate_answers_and_distractors,
    verify_template_structure,
)
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding


def semantic_evidence(candidate, required: int = 3) -> ToolEvidence:
    return ToolEvidence(
        tool=MATH_ANSWERS_TOOL,
        version=MATH_TOOL_VERSION,
        status="passed",
        details=validate_answers_and_distractors(candidate, required),
    )


def structural_evidence(candidate) -> ToolEvidence:
    return ToolEvidence(
        tool=MATH_STRUCTURE_TOOL,
        version=MATH_TOOL_VERSION,
        status="passed",
        details=verify_template_structure(candidate),
    )


def test_structure_accepts_the_supported_template() -> None:
    candidate = math_candidate()

    details = verify_template_structure(candidate)

    assert details["parameters"] == 3
    assert details["combinations"] == 8
    assert details["expressions_checked"] == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"answer_expression": "a ** 2"},
        {"distractors": [{"expression": "unknown(a)", "reason_template": "Bad."}]},
        {"distractors": [{"expression": "a + 1", "reason_template": "Uses {d}."}]},
    ],
)
def test_structure_rejects_unsupported_expressions_and_placeholders(
    overrides,
) -> None:
    candidate = math_candidate(**overrides)

    with pytest.raises(MathToolFailure):
        verify_template_structure(candidate)


def test_answer_check_enumerates_the_bounded_domain() -> None:
    candidate = math_candidate()

    details = validate_answers_and_distractors(candidate, 3)

    assert details["checking_mode"] == "exhaustive_domain"
    assert details["combinations_checked"] == details["max_combinations"] == 8
    assert details["seed"] == 0
    assert [item["expression"] for item in details["selected_distractors"]] == [
        "(c + b) / a",
        "(c - b) * 2",
        "(c - b + 1) / a",
    ]


def test_answer_check_selects_only_the_required_checked_recipes() -> None:
    candidate = math_candidate()

    details = validate_answers_and_distractors(candidate, 2)

    assert len(details["selected_distractors"]) == 2
    assert (
        candidate.distractors[2].model_dump(mode="json")
        not in details["selected_distractors"]
    )


def test_answer_check_rejects_a_distractor_that_coincides_for_one_combination() -> None:
    candidate = math_candidate(
        parameters=[
            {"name": "a", "values": [1, 2]},
            {"name": "b", "values": [2, 4]},
            {"name": "c", "values": [5, 7]},
        ],
        distractors=[
            {"expression": "(c - b)", "reason_template": "Forgets to divide by a."},
            {"expression": "(c + b) / a", "reason_template": "Adds b."},
            {"expression": "(c - b + 1) / a", "reason_template": "Off by one."},
        ],
    )

    with pytest.raises(MathToolFailure) as failure:
        validate_answers_and_distractors(candidate, 3)

    assert failure.value.code == "DISTRACTOR_MATCHES_ANSWER"
    assert failure.value.context["failing_parameters"]["a"] == 1


def test_answer_check_rejects_pairwise_distractor_collisions() -> None:
    candidate = math_candidate(
        distractors=[
            {"expression": "(c + a)", "reason_template": "Adds a."},
            {"expression": "(a + c)", "reason_template": "Also adds a."},
            {"expression": "(c - b + 1) / a", "reason_template": "Off by one."},
        ]
    )

    with pytest.raises(MathToolFailure) as failure:
        validate_answers_and_distractors(candidate, 3)

    assert failure.value.code == "DISTRACTOR_COLLISION"


def test_answer_check_rejects_a_recipe_that_does_not_solve_the_equation() -> None:
    candidate = math_candidate(answer_expression="(c + b) / a")

    with pytest.raises(MathToolFailure) as failure:
        validate_answers_and_distractors(candidate, 3)

    assert failure.value.code == "ANSWER_INCORRECT"
    assert failure.value.context["failing_parameters"]["a"] in {2, 3}
    assert failure.value.context["expected"] != failure.value.context["actual"]


def test_answer_check_accepts_an_equivalent_exact_form() -> None:
    candidate = math_candidate(answer_expression="c / a - b / a")

    details = validate_answers_and_distractors(candidate, 3)

    assert details["combinations_checked"] == 8


def test_answer_check_rejects_insufficient_distractors() -> None:
    candidate = math_candidate(
        distractors=[
            {"expression": "(c + b) / a", "reason_template": "Adds b."},
        ]
    )

    with pytest.raises(MathToolFailure) as failure:
        validate_answers_and_distractors(candidate, 3)

    assert failure.value.code == "INSUFFICIENT_DISTRACTORS"


def test_finalize_rejects_missing_or_failed_technical_evidence() -> None:
    candidate = math_candidate()
    semantic = semantic_evidence(candidate)

    with pytest.raises(ValueError, match="Missing exhaustive"):
        MathDomain().finalize_checked_template(
            candidate, [structural_evidence(candidate)]
        )

    with pytest.raises(ValueError, match="Missing passing template-structure"):
        MathDomain().finalize_checked_template(candidate, [semantic])

    failed_structure = ToolEvidence(
        tool=MATH_STRUCTURE_TOOL,
        version=MATH_TOOL_VERSION,
        status="failed",
        findings=[ToolFinding(code="TEMPLATE_INVALID", message="Bad structure")],
    )
    with pytest.raises(ValueError, match="All selected checks must pass"):
        MathDomain().finalize_checked_template(candidate, [failed_structure, semantic])


def test_finalize_rejects_malformed_or_foreign_selected_distractors() -> None:
    candidate = math_candidate()
    semantic = semantic_evidence(candidate)
    missing = semantic.model_copy(update={"details": {}})

    with pytest.raises(ValueError, match="selection is missing"):
        MathDomain().finalize_checked_template(
            candidate, [structural_evidence(candidate), missing]
        )

    details = copy.deepcopy(semantic.details)
    details["selected_distractors"][0] = {
        "expression": "a + b + c",
        "reason_template": "Not in the proposal.",
    }
    foreign = semantic.model_copy(update={"details": details})
    with pytest.raises(ValueError, match="not checked proposal recipes"):
        MathDomain().finalize_checked_template(
            candidate, [structural_evidence(candidate), foreign]
        )


def test_finalize_accepts_complete_evidence_and_keeps_advisory_failures() -> None:
    candidate = math_candidate()
    semantic = semantic_evidence(candidate)
    difficulty = assess_template_difficulty(candidate)
    # Force an advisory mismatch without changing the checked content.
    failed_advisory = difficulty.model_copy(
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
                **difficulty.details,
                "template_sha256": template_sha256(candidate),
            },
        }
    )

    artifact = MathDomain().finalize_checked_template(
        candidate,
        [structural_evidence(candidate), semantic, failed_advisory],
    )

    assert artifact.template.distractors == candidate.distractors
    assert artifact.validation.combinations_checked == 8
    assert artifact.validation.max_combinations == 8
    assert {item.check for item in artifact.validation.evidence} == {
        MATH_ANSWERS_TOOL,
        MATH_DIFFICULTY_TOOL,
        MATH_STRUCTURE_TOOL,
    }
    saved = next(
        item
        for item in artifact.validation.evidence
        if item.check == MATH_DIFFICULTY_TOOL
    )
    assert saved.status == "failed"


def test_relevance_scores_only_candidate_text() -> None:
    candidate = math_candidate()

    matched = assess_template_relevance(
        candidate, "Write a linear equation question for x."
    )
    mismatch = assess_template_relevance(candidate, "Label a photosynthesis diagram.")
    no_keywords = assess_template_relevance(candidate, "the and for")

    assert matched.status == "passed"
    assert matched.details["relevant"] is True
    assert mismatch.status == "failed"
    assert mismatch.details["relevant"] is False
    assert no_keywords.status == "error"
    assert no_keywords.details["relevance_outcome"]["error_code"] == (
        "RELEVANCE_NO_KEYWORDS"
    )


def test_difficulty_bands_follow_the_documented_heuristic() -> None:
    easy = math_candidate(
        difficulty="easy",
        parameters=[
            {"name": "a", "values": [2]},
            {"name": "b", "values": [2]},
            {"name": "c", "values": [5]},
        ],
    )
    medium = math_candidate(
        difficulty="medium",
        parameters=[
            {"name": "a", "values": [2, 3]},
            {"name": "b", "values": [-3]},
            {"name": "c", "values": [5]},
        ],
    )
    hard = math_candidate(
        difficulty="hard",
        parameters=[
            {"name": "a", "values": [10, 11, 12, 13, 14]},
            {"name": "b", "values": [-4, -3, -2, -1]},
            {"name": "c", "values": [5, 6, 7]},
        ],
    )

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


def test_finalize_only_keeps_checked_distractor_recipes() -> None:
    candidate = math_candidate(
        distractors=[
            *math_payload()["distractors"],
            {"expression": "(c - b) / a - 1", "reason_template": "Subtracts one."},
        ]
    )
    semantic = semantic_evidence(candidate, required=3)

    artifact = MathDomain().finalize_checked_template(
        candidate, [structural_evidence(candidate), semantic]
    )

    assert len(artifact.template.distractors) == 3
    assert artifact.template.distractors == candidate.distractors[:3]
