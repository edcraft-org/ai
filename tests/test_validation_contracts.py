import pytest

from edcraft_validator.application.authoring_contracts import CheckExecution
from edcraft_validator.mcp.evidence import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationFailure


@pytest.mark.parametrize("status", ["failed", "error"])
def test_unsuccessful_tool_evidence_never_passes(status):
    execution = CheckExecution(
        call_id="1",
        tool="answer",
        candidate_digest="abc",
        requested_arguments="{}",
        evidence=ToolEvidence(
            tool="answer",
            version="1",
            status=status,
            findings=[{"code": "TEST_FAILURE", "message": "failed"}],
        ),
    )
    assert not execution.passed


def test_missing_evidence_never_passes():
    assert not CheckExecution(
        call_id="1", tool="answer", candidate_digest="abc", requested_arguments="{}"
    ).passed


def test_protocol_error_cannot_be_overridden_by_passing_evidence():
    execution = CheckExecution(
        call_id="1",
        tool="answer",
        candidate_digest="abc",
        requested_arguments="{}",
        error="version mismatch",
        evidence=ToolEvidence(tool="answer", version="1", status="passed"),
    )
    assert not execution.passed


def test_domain_failure_owns_its_context():
    context = {"inputs": {"a": 1}}
    failure = ValidationFailure("bad answer", code="ANSWER_MISMATCH", context=context)
    context["inputs"]["a"] = 2
    assert failure.context == {"inputs": {"a": 1}}
    assert failure.code == "ANSWER_MISMATCH"
