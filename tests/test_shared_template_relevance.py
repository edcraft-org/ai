"""Shared template relevance evidence reused by capability-selected domains."""

from edcraft_validator.application.template_relevance import assess_template_relevance
from edcraft_validator.validation.check_names import TEMPLATE_RELEVANCE_CHECK
from tests.test_code_relevance import Decisions

SUBJECT = "a" * 64


async def test_shared_template_relevance_is_advisory_passing_evidence() -> None:
    evidence = await assess_template_relevance(
        subject_sha256=SUBJECT,
        author_request="Write a linear equation question for x.",
        question_text="Solve for x: 2x + 4 = 10",
        decision_provider_factory=Decisions,
    )

    assert evidence.tool == TEMPLATE_RELEVANCE_CHECK
    assert evidence.status == "passed"
    assert evidence.details["advisory"] is True
    assert evidence.details["subject_sha256"] == SUBJECT
    assert evidence.details["relevance_outcome"]["status"] == "assessed"
    assert evidence.details["relevant"] is True


async def test_shared_template_relevance_mismatch_never_reads_as_technical() -> None:
    evidence = await assess_template_relevance(
        subject_sha256=SUBJECT,
        author_request="Label a photosynthesis diagram.",
        question_text="Solve for x: 2x + 4 = 10",
        decision_provider_factory=lambda: Decisions(0.0),
    )

    assert evidence.status == "failed"
    assert [finding.code for finding in evidence.findings] == ["RELEVANCE_MISMATCH"]
    assert evidence.details["advisory"] is True
    assert evidence.details["relevance_outcome"]["unavailable"] is False


async def test_shared_template_relevance_error_is_unavailable_advisory() -> None:
    evidence = await assess_template_relevance(
        subject_sha256=SUBJECT,
        author_request="Write a linear equation question for x.",
        question_text="Solve for x: 2x + 4 = 10",
        decision_provider_factory=lambda: Decisions(RuntimeError("judge down")),
    )

    assert evidence.status == "error"
    assert evidence.details["advisory"] is True
    outcome = evidence.details["relevance_outcome"]
    assert outcome["status"] == "unavailable"
    assert outcome["unavailable"] is True
    assert outcome["error_code"] == "RELEVANCE_FAILED"
