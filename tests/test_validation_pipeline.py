from dataclasses import dataclass

import pytest

from edcraft_validator.validation import ValidationFailure, ValidationPipeline
from edcraft_validator.validation.contracts import CheckResult, ValidationPolicy


def test_pipeline_records_success_for_any_domain() -> None:
    class SymbolicCheck:
        name = "symbolic_equivalence"
        assurance = "proof"

        def run(self, context):
            context["answer"] = 42
            return CheckResult(details={"tool": "example"})

    context = {}
    report = ValidationPipeline().validate(
        context=context,
        checks=[SymbolicCheck()],
        policy=ValidationPolicy(frozenset({"symbolic_equivalence"})),
    )
    assert report.accepted
    assert context["answer"] == 42
    assert report.evidence[0].check == "symbolic_equivalence"
    assert report.evidence[0].status == "passed"
    assert report.evidence[0].details == {"tool": "example"}


def test_pipeline_attaches_evidence_to_a_structured_failure() -> None:
    class DimensionalCheck:
        name = "dimensional_consistency"
        assurance = "proof"

        def run(self, context):
            raise ValidationFailure(
                "units do not match",
                code="UNIT_MISMATCH",
                field="answer",
                context={"tool": "unit-checker", "expected_unit": "m/s"},
            )

    report = ValidationPipeline().validate(
        context=[],
        checks=[ExampleCheck("structure"), DimensionalCheck(), ExampleCheck("later")],
        policy=ValidationPolicy(frozenset({"dimensional_consistency"})),
    )
    with pytest.raises(ValidationFailure) as error:
        report.raise_for_failure()
    assert [item.check for item in report.evidence] == [
        "structure",
        "dimensional_consistency",
    ]
    assert not report.accepted
    assert error.value.code == "UNIT_MISMATCH"
    assert error.value.field == "answer"
    assert error.value.evidence == report.evidence
    evidence = error.value.evidence[-1]
    assert evidence.status == "failed"
    assert evidence.issues[0].code == "UNIT_MISMATCH"
    assert evidence.details["expected_unit"] == "m/s"
    assert evidence.details["tool"] == "unit-checker"


@dataclass
class ExampleCheck:
    name: str
    outcome: str | None = "passed"
    assurance: str = "bounded"

    def run(self, context):
        context.append(self.name)
        if self.outcome is None:
            return None
        if self.outcome == "timeout":
            raise TimeoutError
        return CheckResult(status=self.outcome)


def test_runner_stops_after_blocking_failure():
    context = []
    report = ValidationPipeline().validate(
        context=context,
        checks=[ExampleCheck("safety", "failed"), ExampleCheck("execution")],
        policy=ValidationPolicy(frozenset({"safety", "execution"})),
    )
    assert context == ["safety"]
    assert report.missing_checks == {"execution"}
    assert not report.accepted
    assert report.evidence[0].duration_ms >= 0


def test_skipped_required_check_is_not_accepted():
    report = ValidationPipeline().validate(
        context=[],
        checks=[ExampleCheck("answer", None)],
        policy=ValidationPolicy(frozenset({"answer"})),
    )
    assert not report.accepted
    assert report.missing_checks == {"answer"}


def test_timeout_is_incomplete():
    report = ValidationPipeline().validate(
        context=[],
        checks=[ExampleCheck("answer", "timeout")],
        policy=ValidationPolicy(frozenset({"answer"})),
    )
    assert not report.accepted
    assert report.evidence[0].status == "incomplete"
    with pytest.raises(ValidationFailure) as error:
        report.raise_for_failure()
    assert error.value.code == "CHECK_TIMEOUT"
    assert error.value.evidence == report.evidence


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_optional_failure_stops_checks_and_runner_is_reusable(status):
    runner = ValidationPipeline()
    context = []
    report = runner.validate(
        context=context,
        checks=[ExampleCheck("style", status), ExampleCheck("answer")],
        policy=ValidationPolicy(frozenset({"answer"})),
    )
    assert not report.accepted
    assert context == ["style"]
    second = runner.validate(
        context=[],
        checks=[],
        policy=ValidationPolicy(frozenset({"answer"})),
    )
    assert not second.accepted
    assert second.evidence == []


def test_unexpected_check_bug_is_not_treated_as_template_rejection():
    class BrokenCheck:
        name = "broken"
        assurance = "bounded"

        def run(self, context):
            raise RuntimeError("implementation bug")

    with pytest.raises(RuntimeError, match="implementation bug"):
        ValidationPipeline().validate(
            context=[],
            checks=[BrokenCheck()],
            policy=ValidationPolicy(frozenset({"broken"})),
        )
