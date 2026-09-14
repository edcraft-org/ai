import pytest

from edcraft_validator.validation.contracts import (
    ValidationEvidence,
    ValidationFailure,
    ValidationPolicy,
    ValidationReport,
)


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_required_check_must_pass(status):
    report = ValidationReport(
        evidence=[
            ValidationEvidence(check="answer", status=status, assurance="bounded")
        ],
        policy=ValidationPolicy(required_checks=frozenset({"answer"})),
    )
    assert not report.accepted
    with pytest.raises(ValidationFailure):
        report.raise_for_failure()


def test_missing_check_cannot_pass():
    report = ValidationReport([], ValidationPolicy(frozenset({"answer"})))
    assert report.missing_checks == {"answer"}
    assert not report.accepted


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_unsuccessful_optional_check_rejects_report(status):
    report = ValidationReport(
        [
            ValidationEvidence(check="answer", status="passed", assurance="exhaustive"),
            ValidationEvidence(check="style", status=status, assurance="heuristic"),
        ],
        ValidationPolicy(frozenset({"answer"})),
    )
    assert not report.accepted
