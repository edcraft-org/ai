"""Owner-scoped immutable check storage and mutable template records."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edcraft_validator.application.check_pilot.errors import (
    PilotConflict,
    PilotInputError,
    PilotNotFound,
)
from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    CheckRecord,
    CheckRef,
    PilotTemplateDefinition,
    PilotTemplateRecord,
    Qualification,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.application.check_pilot.storage import (
    NULL_TEMPLATE_SHA256,
    PilotStore,
    check_content_sha256,
    template_definition_sha256,
    template_record_sha256,
)


def qualification(status: str = "passed") -> Qualification:
    findings = (
        ["No counterexample found in sampled cases"] if status == "passed" else ["x"]
    )
    return Qualification(
        status=status,
        accepted_cases=20,
        execution_calls=100,
        seed=1,
        max_examples=20,
        max_execution_calls=600,
        timeout_seconds=30.0,
        counterexample=None,
        findings=findings,
        versions={"polynomial_oracle": "coefficient-arithmetic/1"},
    )


def recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        steps=[
            RecipeStep(
                id="d1",
                operation="poly.differentiate",
                version="1",
                arguments={
                    "polynomial": RecipeArgument(source="input", name="problem")
                },
            ),
            RecipeStep(
                id="out",
                operation="poly.equivalent",
                version="1",
                arguments={
                    "expected": RecipeArgument(source="step", name="d1"),
                    "actual": RecipeArgument(source="input", name="candidate"),
                },
            ),
        ],
        output="out",
    )


def check_record(*, description: str = "Differentiate a bounded polynomial."):
    definition = recipe().model_dump(mode="json")
    scope = {
        "subject": "univariate-real-polynomial",
        "operation": "differentiate",
        "variable": "x",
        "max_degree": 5,
        "max_abs_coefficient": 20,
    }
    digest = check_content_sha256(
        title="Polynomial derivative",
        description=description,
        scope=scope,
        definition=definition,
    )
    return CheckRecord(
        check_ref=CheckRef(check_id=f"chk_{digest[:24]}", version="1", sha256=digest),
        title="Polynomial derivative",
        description=description,
        scope=scope,
        definition=definition,
        qualification=qualification(),
        provenance={"provider": "stub", "model": "stub-model"},
        created_at=datetime.now(UTC).isoformat(),
    )


def template_definition():
    return PilotTemplateDefinition.model_validate(
        {
            "family": {
                "degree": 1,
                "coefficients": [
                    {"exponent": 0, "values": [-2, 0, 2]},
                    {"exponent": 1, "values": [1, 3]},
                ],
                "num_distractors": 3,
            }
        }
    )


def template_record(check: CheckRecord):
    definition = template_definition()
    digest = template_definition_sha256(definition)
    return PilotTemplateRecord(
        template_id=f"tpl_{digest[:24]}",
        template_sha256=digest,
        prompt="Author a linear polynomial differentiation template",
        status="ready",
        approval="unreviewed",
        reused_check=True,
        check=check,
        template=definition.model_dump(mode="json"),
        qualification=qualification(),
        findings=[],
        created_at=datetime.now(UTC).isoformat(),
    )


def test_check_storage_is_owner_scoped_and_survives_restart(tmp_path: Path):
    store = PilotStore(tmp_path)
    record = check_record()
    saved = store.save_check("owner-a", record)
    assert saved == record

    restarted = PilotStore(tmp_path)
    assert restarted.get_check("owner-a", record.check_ref.check_id) == record
    assert [item.check_ref for item in restarted.list_checks("owner-a")] == [
        record.check_ref
    ]
    assert restarted.list_checks("owner-b") == []
    with pytest.raises(PilotNotFound):
        restarted.get_check("owner-b", record.check_ref.check_id)


def test_identical_resave_is_idempotent_but_immutable_version_conflicts(
    tmp_path: Path,
):
    store = PilotStore(tmp_path)
    record = check_record()
    store.save_check("owner", record)
    assert store.save_check("owner", record) == record

    changed = check_record(description="A different description")
    conflicting = record.model_copy(
        update={
            "check_ref": record.check_ref.model_copy(
                update={"sha256": changed.check_ref.sha256}
            ),
            "description": changed.description,
        }
    )
    with pytest.raises(PilotConflict):
        store.save_check("owner", conflicting)
    assert store.get_check("owner", record.check_ref.check_id) == record


def test_concurrent_identical_writes_keep_one_valid_file(tmp_path: Path):
    store = PilotStore(tmp_path)
    record = check_record()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.save_check("owner", record), range(16)))
    assert results == [record] * 16
    assert store.get_check("owner", record.check_ref.check_id) == record


def test_read_validates_envelope_and_content_hash(tmp_path: Path):
    store = PilotStore(tmp_path)
    record = check_record()
    store.save_check("owner", record)
    check_id = record.check_ref.check_id
    path = next(tmp_path.rglob("v1.json"))
    raw = json.loads(path.read_text())
    raw["record"]["description"] = "tampered"
    path.write_text(json.dumps(raw))

    with pytest.raises(PilotConflict, match="integrity"):
        store.get_check("owner", check_id)

    raw["record"]["description"] = record.description
    raw["record"]["definition"]["steps"][0]["operation"] = "poly.identity"
    path.write_text(json.dumps(raw))
    with pytest.raises(PilotConflict, match="integrity"):
        store.get_check("owner", check_id)


def test_unqualified_checks_and_unsafe_identifiers_are_rejected(tmp_path: Path):
    store = PilotStore(tmp_path)
    with pytest.raises(PilotInputError):
        store.save_check(
            "owner",
            check_record().model_copy(
                update={"qualification": qualification("failed")}
            ),
        )
    for owner in ("", "   ", "x" * 201):
        with pytest.raises(PilotInputError):
            store.list_checks(owner)
    with pytest.raises(PilotNotFound):
        store.get_check("owner", "../escape")
    with pytest.raises(PilotNotFound):
        store.get_check("owner", "chk_not-hex")


def test_template_storage_update_is_compare_and_swap_and_owner_scoped(
    tmp_path: Path,
):
    store = PilotStore(tmp_path)
    check = store.save_check("owner-a", check_record())
    record = template_record(check)
    saved = store.save_template("owner-a", record)
    assert saved == record
    assert PilotStore(tmp_path).get_template("owner-a", record.template_id) == record

    with pytest.raises(PilotNotFound):
        store.get_template("owner-b", record.template_id)
    with pytest.raises(PilotNotFound):
        store.get_template("owner-b", "../escape")

    approved = record.model_copy(update={"approval": "approved"})
    expected = template_record_sha256(record)
    assert (
        store.replace_template(
            "owner-a", approved, expected_record_sha256=expected
        ).approval
        == "approved"
    )
    with pytest.raises(PilotConflict):
        store.replace_template(
            "owner-a",
            record.model_copy(update={"approval": "rejected"}),
            expected_record_sha256=expected,
        )


def test_template_digest_and_record_hash_are_validated_on_read(tmp_path: Path):
    store = PilotStore(tmp_path)
    check = store.save_check("owner", check_record())
    record = template_record(check)
    store.save_template("owner", record)
    path = next(tmp_path.rglob("template.json"))
    raw = json.loads(path.read_text())
    raw["record"]["template"]["family"]["degree"] = 2
    path.write_text(json.dumps(raw))
    with pytest.raises(PilotConflict, match="integrity"):
        store.get_template("owner", record.template_id)


def test_empty_template_digest_is_stable_for_error_records(tmp_path: Path):
    store = PilotStore(tmp_path)
    record = PilotTemplateRecord(
        template_id="tpl_" + "a" * 24,
        template_sha256=NULL_TEMPLATE_SHA256,
        prompt="Unsupported request",
        status="error",
        approval="unreviewed",
        reused_check=False,
        check=None,
        template=None,
        qualification=None,
        findings=["provider failed"],
        created_at=datetime.now(UTC).isoformat(),
    )
    store.save_template("owner", record)
    assert store.get_template("owner", record.template_id) == record


LEGACY_TEMPLATE = {
    "schema_version": "pilot-template/1",
    "renderer_version": "polynomial-mcq/1",
    "scope": {
        "subject": "univariate-real-polynomial",
        "operation": "differentiate",
        "variable": "x",
        "max_degree": 5,
        "max_abs_coefficient": 20,
    },
    "family": {
        "schema_version": "polynomial-family/1",
        "variable": "x",
        "degree": 2,
        "coefficients": [
            {"exponent": 0, "values": [-3, -1, 0, 2]},
            {"exponent": 1, "values": [-2, 0, 1, 2]},
            {"exponent": 2, "values": [1, 2, 3]},
        ],
        "num_distractors": 3,
    },
}


def _canonical(value) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def test_legacy_v1_template_and_record_hashes_survive_additive_fields():
    definition = PilotTemplateDefinition.model_validate(LEGACY_TEMPLATE)
    assert definition.model_dump(mode="json", exclude_none=True) == LEGACY_TEMPLATE
    assert template_definition_sha256(definition) == _canonical(LEGACY_TEMPLATE)
    # This digest is the frozen pre-catalogue value stored in the backend fixture.
    assert (
        template_definition_sha256(definition)
        == "cad86505c18298d465e932e6cae78f6344fa572c96ed39bc4df9504e6cb0acac"
    )

    legacy_record = {
        "template_id": "tpl_" + "a" * 24,
        "template_sha256": template_definition_sha256(definition),
        "prompt": "Differentiate a polynomial",
        "status": "ready",
        "approval": "approved",
        "reused_check": False,
        "check": check_record().model_dump(mode="json"),
        "template": LEGACY_TEMPLATE,
        "qualification": qualification().model_dump(mode="json"),
        "findings": [],
        "created_at": datetime.now(UTC).isoformat(),
        "scope": LEGACY_TEMPLATE["scope"],
        "provenance": {"role": "template-author"},
    }
    parsed = PilotTemplateRecord.model_validate(legacy_record)
    assert parsed.selection is None
    # Additive null diagnostics are not part of the canonical reloaded hash.
    assert template_record_sha256(parsed) == template_record_sha256(
        PilotTemplateRecord.model_validate(
            parsed.model_dump(mode="json", exclude_none=True)
        )
    )
