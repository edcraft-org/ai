"""Generation runs the whole solve batch in one disposable worker request."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_check_pilot_application import app, author
from test_check_pilot_legacy_replay import legacy_records
from test_check_pilot_solve_flow import solve_provider

import edcraft_validator.application.check_pilot.generation as generation_module
import edcraft_validator.application.check_pilot.question as question_module
import edcraft_validator.application.check_pilot.solution_sets as solution_sets_module
from edcraft_validator.application.check_pilot import (
    CheckPilotApplication,
    PilotConflict,
    PilotTemplateRecord,
)
from edcraft_validator.application.check_pilot.models import PolynomialScope
from edcraft_validator.application.check_pilot.storage import (
    PilotStore,
    check_content_sha256,
)


def approved_solve_template(
    tmp_path: Path,
) -> tuple[CheckPilotApplication, PilotTemplateRecord]:
    application = app(tmp_path)
    record = author(
        application,
        solve_provider(),
        prompt="Solve a bounded quadratic equation completely",
    )
    assert record.status == "ready"
    assert record.check is not None
    application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    return application, record


def test_generate_never_calls_host_solve_builder_guard_or_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, record = approved_solve_template(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("host symbolic solve generation path was called")

    for module in (generation_module, question_module):
        for name in ("build_solve_instance", "guard_solve_instance"):
            monkeypatch.setattr(module, name, forbidden, raising=False)
    for module in (generation_module, solution_sets_module):
        monkeypatch.setattr(
            module, "solve_relation_independently", forbidden, raising=False
        )

    calls: list[dict[str, object]] = []
    real_worker = generation_module.run_pilot_isolated

    def observe(payload: dict[str, object], *, timeout_seconds: float):
        calls.append(dict(payload))
        return real_worker(payload, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(generation_module, "run_pilot_isolated", observe)

    batch = application.generate("owner", record.template_id, seed=42, quantity=6)

    assert len(batch.questions) == 6
    assert len(calls) == 1
    assert calls[0]["operation"] == "generate_batch"
    assert calls[0]["template_id"] == record.template_id
    assert calls[0]["seed"] == 42
    assert calls[0]["quantity"] == 6


def test_real_worker_timeout_returns_no_partial_batch(tmp_path: Path) -> None:
    application, record = approved_solve_template(tmp_path)

    with pytest.raises(
        PilotConflict,
        match="hard time limit.*no questions were returned",
    ):
        generation_module.generate_batch(
            application.store,
            "owner",
            record.template_id,
            seed=42,
            quantity=10,
            timeout_seconds=0.01,
        )


def test_parent_rejects_a_stored_scope_that_does_not_cover_the_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check, template = legacy_records()
    narrow_scope = PolynomialScope(max_degree=1, max_abs_coefficient=20)
    scope = narrow_scope.model_dump(mode="json")
    digest = check_content_sha256(
        title=check.title,
        description=check.description,
        scope=scope,
        definition=check.definition,
    )
    narrow_check = check.model_copy(
        update={
            "check_ref": check.check_ref.model_copy(
                update={"check_id": f"chk_{digest[:24]}", "sha256": digest}
            ),
            "scope": scope,
        }
    )
    narrow_template = template.model_copy(update={"check": narrow_check})
    store = PilotStore(tmp_path)
    store.save_check("owner", narrow_check)
    store.save_template("owner", narrow_template)

    def fail_if_spawned(*args: object, **kwargs: object) -> object:
        pytest.fail("an inapplicable stored template must not start a worker")

    monkeypatch.setattr(generation_module, "run_pilot_isolated", fail_if_spawned)

    with pytest.raises(PilotConflict, match="does not cover this template"):
        generation_module.generate_batch(
            store,
            "owner",
            narrow_template.template_id,
            seed=42,
            quantity=3,
        )
