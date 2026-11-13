"""Boundary coverage for the public maximum pilot batch and recipe cap."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from test_check_pilot_application import (
    ScriptedProvider,
    app,
    author,
    valid_recipe,
    valid_template_proposal,
)

import edcraft_validator.application.check_pilot.qualification as qualification_module
from edcraft_validator.application.check_pilot.isolation import (
    PilotWorkerError,
    run_pilot_isolated,
)
from edcraft_validator.application.check_pilot.polynomial import parse_polynomial


def test_public_maximum_batch_of_100_with_five_distractors_succeeds(
    tmp_path: Path,
):
    application = app(tmp_path)
    provider = ScriptedProvider(
        template=valid_template_proposal(
            degree=1,
            constants=list(range(-6, 6)),
            leading=[-4, -3, -2, -1, 1, 2, 3, 4, 5],
        )
    )
    record = author(application, provider, num_distractors=5)
    assert record.status == "ready"
    assert record.template is not None
    assignment_count = math.prod(
        len(domain["values"]) for domain in record.template["family"]["coefficients"]
    )
    assert assignment_count >= 100
    application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )

    batch = application.generate("owner", record.template_id, seed=42, quantity=100)

    assert len(batch.questions) == 100
    assert batch.shortfall == 0
    assert all(len(question.choices) == 6 for question in batch.questions)


def test_recipe_case_executor_accepts_six_hundred_valid_cases():
    case = (parse_polynomial("x"), parse_polynomial("1"))

    results = qualification_module.execute_recipe_cases_isolated(
        valid_recipe(),
        [case] * 600,
        timeout_seconds=30,
    )

    assert len(results) == 600
    assert all(result.verdict for result in results)


def test_recipe_case_executor_rejects_601_cases_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_if_spawned(*args, **kwargs):
        pytest.fail("a rejected batch must not start an isolated worker")

    monkeypatch.setattr(qualification_module, "run_pilot_isolated", fail_if_spawned)
    case = (parse_polynomial("x"), parse_polynomial("1"))

    with pytest.raises(ValueError, match="at most 600 recipe cases"):
        qualification_module.execute_recipe_cases_isolated(
            valid_recipe(),
            [case] * 601,
            timeout_seconds=30,
        )


def test_worker_rejects_a_601_case_request_that_bypasses_the_helper():
    with pytest.raises(PilotWorkerError, match="at most 600"):
        run_pilot_isolated(
            {
                "operation": "execute_recipe_cases",
                "definition": valid_recipe().model_dump(mode="json"),
                "cases": [{"problem": "x", "candidate": "1"}] * 601,
            },
            timeout_seconds=30,
        )
