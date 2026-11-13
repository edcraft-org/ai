"""Lifecycle regressions: rejection, auto-rejection, evidence freeze and scopes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_check_pilot_application import (
    ScriptedProvider,
    app,
    author,
    unsupported_recipe,
    valid_recipe,
    wrong_recipe,
)
from test_check_pilot_storage import check_record, template_record

from edcraft_validator.application.check_pilot.contracts import (
    DIFFERENTIATE_CONTRACT,
    get_contract,
)
from edcraft_validator.application.check_pilot.errors import (
    PilotConflict,
    PilotInputError,
)
from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    CheckPlanProposal,
    CheckRecord,
    CheckRef,
    Qualification,
)
from edcraft_validator.application.check_pilot.storage import (
    PilotStore,
    check_content_sha256,
    template_record_sha256,
)

# --- Fix 1: rejection does not require a qualified check -------------------


def test_draft_without_check_can_be_rejected_but_not_approved(tmp_path: Path):
    application = app(tmp_path)
    provider = ScriptedProvider(
        plan=CheckPlanProposal(
            supported=False,
            development_needed="This request needs a capability outside the pilot.",
        )
    )
    record = author(application, provider)
    assert record.check is None
    assert record.status == "needs_review"
    assert record.approval == "unreviewed"

    # Approving still requires a qualified check pinned by its exact hash.
    with pytest.raises(PilotConflict):
        application.decide(
            "owner",
            record.template_id,
            template_sha256=record.template_sha256,
            check_sha256="a" * 64,
            decision="approved",
        )
    with pytest.raises(PilotInputError):
        application.decide(
            "owner",
            record.template_id,
            template_sha256=record.template_sha256,
            check_sha256=None,
            decision="approved",
        )

    # Rejection only needs the current template hash.
    with pytest.raises(PilotConflict):
        application.decide(
            "owner",
            record.template_id,
            template_sha256="0" * 64,
            decision="rejected",
        )
    rejected = application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        decision="rejected",
    )
    assert rejected.approval == "rejected"
    assert rejected.status == "needs_review"
    assert application.get_template("owner", record.template_id).approval == "rejected"


# --- Fix 2: failed qualification is auto-rejected, errors stay retryable ----


def failed_template_qualification(*args, **kwargs) -> Qualification:
    return Qualification(
        status="failed",
        accepted_cases=4,
        execution_calls=12,
        seed=1,
        max_examples=8,
        max_execution_calls=800,
        timeout_seconds=30.0,
        counterexample={"reason": "pinned recipe accepted a distractor"},
        findings=["counterexample: pinned recipe accepted a distractor"],
        versions={"question_builder": "polynomial-mcq/1"},
    )


def test_failed_template_qualification_is_auto_rejected(tmp_path: Path, monkeypatch):
    from edcraft_validator.application.check_pilot import authoring as module

    monkeypatch.setattr(
        module, "qualify_structured_template", failed_template_qualification
    )
    application = app(tmp_path)
    record = author(application, ScriptedProvider())

    assert record.status == "needs_review"
    assert record.qualification is not None
    assert record.qualification.status == "failed"
    assert record.approval == "rejected"
    # Failure evidence stays available for inspection.
    assert record.findings
    assert any("counterexample" in finding for finding in record.findings)

    with pytest.raises(PilotConflict):
        application.decide(
            "owner",
            record.template_id,
            template_sha256=record.template_sha256,
            check_sha256=record.check.check_ref.sha256,
            decision="approved",
        )
    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=1)


def test_failed_check_qualification_is_auto_rejected(tmp_path: Path):
    provider = ScriptedProvider(
        check=CheckAuthorProposal(
            title="Wrong derivative",
            description="This recipe differentiates twice.",
            recipe=wrong_recipe(),
        )
    )
    record = author(app(tmp_path), provider)

    assert record.status == "needs_review"
    assert record.check is None
    assert record.check_qualification is not None
    assert record.check_qualification.status == "failed"
    assert record.approval == "rejected"
    assert record.findings


@pytest.mark.parametrize(
    "provider",
    [
        ScriptedProvider(check_errors=1),
        ScriptedProvider(template_errors=1),
    ],
    ids=["check-worker-error", "template-worker-error"],
)
def test_worker_error_stays_unreviewed_for_retry(tmp_path: Path, provider):
    record = author(app(tmp_path), provider)

    assert record.status == "error"
    assert record.approval == "unreviewed"


def test_compile_error_stays_unreviewed(tmp_path: Path):
    provider = ScriptedProvider(
        check=CheckAuthorProposal(
            title="Unsupported integration check",
            description="This recipe asks for an operation outside the pilot.",
            recipe=unsupported_recipe(),
        )
    )
    record = author(app(tmp_path), provider)

    assert record.status == "needs_review"
    assert record.check_qualification is not None
    assert record.check_qualification.status == "error"
    assert record.approval == "unreviewed"


# --- Fix 3: approval may not change frozen evidence -------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "A rewritten prompt"),
        ("findings", ["rewritten finding"]),
        ("created_at", "2020-01-01T00:00:00+00:00"),
    ],
)
def test_approval_cannot_change_frozen_evidence(
    tmp_path: Path, field: str, value: object
):
    store = PilotStore(tmp_path)
    check = store.save_check("owner", check_record())
    record = store.save_template("owner", template_record(check))
    expected = template_record_sha256(record)

    tampered = record.model_copy(update={field: value})
    with pytest.raises(PilotConflict, match="only change the decision"):
        store.replace_template("owner", tampered, expected_record_sha256=expected)
    assert store.get_template("owner", record.template_id) == record

    approved = record.model_copy(update={"approval": "approved"})
    assert (
        store.replace_template(
            "owner", approved, expected_record_sha256=expected
        ).approval
        == "approved"
    )


# --- Fix 4: stored scope must match the trusted contract exactly ------------


def _scoped_check(scope: dict[str, object]) -> CheckRecord:
    definition = valid_recipe().model_dump(mode="json")
    digest = check_content_sha256(
        title="Differentiate a bounded polynomial",
        description="Compare a candidate derivative with a trusted derivative.",
        scope=scope,
        definition=definition,
    )
    return CheckRecord(
        check_ref=CheckRef(check_id=f"chk_{digest[:24]}", version="1", sha256=digest),
        title="Differentiate a bounded polynomial",
        description="Compare a candidate derivative with a trusted derivative.",
        scope=scope,
        definition=definition,
        qualification=Qualification(
            status="passed",
            accepted_cases=20,
            execution_calls=100,
            seed=1,
            max_examples=20,
            max_execution_calls=600,
            timeout_seconds=30.0,
            findings=["No counterexample found in sampled cases"],
        ),
        provenance={"provider": "stub", "model": "stub-model"},
        created_at=datetime.now(UTC).isoformat(),
    )


def _canonical(value: object) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def test_widened_contract_scope_is_rejected_at_write(tmp_path: Path):
    contract = get_contract(DIFFERENTIATE_CONTRACT)
    assert contract is not None
    trusted_scope = contract.scope()

    store = PilotStore(tmp_path)
    store.save_check("owner", _scoped_check(trusted_scope.model_dump(mode="json")))

    widened_scope = trusted_scope.model_copy(update={"max_abs_coefficient": 21})
    with pytest.raises(PilotConflict, match="outside the pilot scope"):
        store.save_check("owner", _scoped_check(widened_scope.model_dump(mode="json")))


def test_widened_contract_scope_is_rejected_on_read(tmp_path: Path):
    contract = get_contract(DIFFERENTIATE_CONTRACT)
    assert contract is not None
    trusted_scope = contract.scope()
    store = PilotStore(tmp_path)
    record = store.save_check(
        "owner", _scoped_check(trusted_scope.model_dump(mode="json"))
    )

    path = next(tmp_path.rglob("v1.json"))
    raw = json.loads(path.read_text())
    widened_scope = trusted_scope.model_copy(update={"max_abs_coefficient": 21})
    raw["record"]["scope"] = widened_scope.model_dump(mode="json")
    # Recompute the stored content digest so only the scope trust check can fail.
    raw["record"]["check_ref"]["sha256"] = check_content_sha256(
        title=raw["record"]["title"],
        description=raw["record"]["description"],
        scope=raw["record"]["scope"],
        definition=raw["record"]["definition"],
    )
    raw["record_sha256"] = _canonical(raw["record"])
    path.write_text(json.dumps(raw))

    with pytest.raises(PilotConflict, match="outside the pilot scope"):
        store.get_check("owner", record.check_ref.check_id)


def test_legacy_scope_may_narrow_but_not_widen_the_contract(tmp_path: Path):
    store = PilotStore(tmp_path)
    legacy = {
        "subject": "univariate-real-polynomial",
        "operation": "differentiate",
        "variable": "x",
        "max_degree": 2,
        "max_abs_coefficient": 10,
    }
    narrower = _scoped_check(legacy)
    store.save_check("owner", narrower)

    widened = _scoped_check({**legacy, "max_abs_coefficient": 21})
    with pytest.raises(PilotConflict, match="outside the pilot scope"):
        store.save_check("owner", widened)
