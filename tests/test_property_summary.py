"""The shared property-check summary shape and its evidence reader."""

import pytest
from pydantic import ValidationError

from edcraft_validator.validation.property_summary import (
    PropertyCheckSummary,
    property_details,
)
from edcraft_validator.validation.validation_contracts import ValidationEvidence

PROPERTY_FIELDS = {
    "checking_mode": "property_based",
    "examples_checked": 4,
    "execution_calls": 4,
    "max_examples": 4,
    "max_execution_calls": 16,
    "timeout_seconds": 15.0,
    "seed": 0,
    "whole_domain": True,
}


def summary(**overrides) -> PropertyCheckSummary:
    payload = {
        **PROPERTY_FIELDS,
        "evidence": [
            ValidationEvidence(check="first_check", status="passed"),
        ],
    }
    payload.update(overrides)
    return PropertyCheckSummary(**payload)


def test_accepts_one_passing_evidence_row_per_check() -> None:
    checked = summary(
        evidence=[
            ValidationEvidence(check="first_check", status="passed"),
            ValidationEvidence(check="second_check", status="passed"),
        ]
    )

    assert checked.examples_checked == 4
    assert checked.whole_domain is True


def test_rejects_duplicate_evidence_checks() -> None:
    with pytest.raises(ValidationError, match="checks must be unique"):
        summary(
            evidence=[
                ValidationEvidence(check="first_check", status="passed"),
                ValidationEvidence(check="first_check", status="passed"),
            ]
        )


def test_rejects_failed_technical_evidence() -> None:
    with pytest.raises(ValidationError, match="passing validation evidence"):
        summary(
            evidence=[
                ValidationEvidence(check="first_check", status="failed"),
            ]
        )


def test_allows_failed_advisory_evidence() -> None:
    checked = summary(
        evidence=[
            ValidationEvidence(check="first_check", status="passed"),
            ValidationEvidence(
                check="second_check",
                status="failed",
                details={"advisory": True},
            ),
        ]
    )

    assert checked.evidence[-1].status == "failed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"examples_checked": 5, "execution_calls": 4},
        {"execution_calls": 17, "max_execution_calls": 16},
    ],
)
def test_rejects_counts_over_the_checking_budget(overrides) -> None:
    with pytest.raises(ValidationError, match="exceed the checking budget"):
        summary(**overrides)


def test_property_details_returns_only_the_property_fields() -> None:
    details = {**PROPERTY_FIELDS, "ir_status": "passed", "declared_domain_size": 9}

    assert property_details(details) == PROPERTY_FIELDS


def test_property_details_reports_every_missing_field() -> None:
    details = {
        key: value for key, value in PROPERTY_FIELDS.items() if key != "timeout_seconds"
    }

    with pytest.raises(
        ValueError, match="property check details are missing: timeout_seconds"
    ):
        property_details(details)
