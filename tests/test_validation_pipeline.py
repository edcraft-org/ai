import pytest

from edcraft_validator.validation import ValidationFailure, ValidationPipeline


def test_pipeline_records_success_for_any_domain() -> None:
    pipeline = ValidationPipeline()

    result = pipeline.check(
        name="symbolic_equivalence",
        assurance="proof",
        details={"tool": "example"},
        operation=lambda: 42,
    )

    assert result == 42
    assert pipeline.evidence[0].check == "symbolic_equivalence"
    assert pipeline.evidence[0].status == "passed"


def test_pipeline_attaches_evidence_to_a_structured_failure() -> None:
    pipeline = ValidationPipeline()

    def reject() -> None:
        raise ValidationFailure(
            "units do not match",
            code="UNIT_MISMATCH",
            field="answer",
            context={"expected_unit": "m/s"},
        )

    with pytest.raises(ValidationFailure) as error:
        pipeline.check(
            name="dimensional_consistency",
            assurance="proof",
            details={"tool": "unit-checker"},
            operation=reject,
        )

    evidence = error.value.evidence[0]
    assert evidence.status == "failed"
    assert evidence.issues[0].code == "UNIT_MISMATCH"
    assert evidence.details["expected_unit"] == "m/s"
