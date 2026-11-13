"""Frozen legacy v1 artifact replay: records and seeded batches stay identical."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from test_check_pilot_storage import LEGACY_TEMPLATE, qualification

from edcraft_validator.application.check_pilot import CheckPilotApplication
from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    CheckRecord,
    CheckRef,
    PilotTemplateDefinition,
    PilotTemplateRecord,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.application.check_pilot.storage import (
    PilotStore,
    check_content_sha256,
    template_definition_sha256,
)

TITLE = "Differentiate a bounded polynomial"
DESCRIPTION = "Compare a candidate derivative with an independently derived polynomial."


def legacy_recipe() -> CheckRecipeDefinition:
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


def legacy_records() -> tuple[CheckRecord, PilotTemplateRecord]:
    definition = legacy_recipe().model_dump(mode="json")
    digest = check_content_sha256(
        title=TITLE,
        description=DESCRIPTION,
        scope=LEGACY_TEMPLATE["scope"],
        definition=definition,
    )
    check = CheckRecord(
        check_ref=CheckRef(check_id=f"chk_{digest[:24]}", version="1", sha256=digest),
        title=TITLE,
        description=DESCRIPTION,
        scope=LEGACY_TEMPLATE["scope"],
        definition=definition,
        qualification=qualification(),
        provenance={"provider": "stub", "model": "legacy-fixture"},
        created_at=datetime.now(UTC).isoformat(),
    )
    template_definition = PilotTemplateDefinition.model_validate(LEGACY_TEMPLATE)
    template = PilotTemplateRecord(
        template_id="tpl_" + "d" * 24,
        template_sha256=template_definition_sha256(template_definition),
        prompt="Differentiate a polynomial",
        status="ready",
        approval="approved",
        reused_check=False,
        check=check,
        template=LEGACY_TEMPLATE,
        qualification=qualification(),
        findings=[],
        created_at=datetime.now(UTC).isoformat(),
        scope=LEGACY_TEMPLATE["scope"],
        provenance={"role": "template-author"},
        check_qualification=qualification(),
    )
    return check, template


def test_legacy_v1_template_replays_the_frozen_seeded_batch(tmp_path: Path):
    check, template = legacy_records()
    assert (
        check.check_ref.sha256
        == "3eeb3ff175761a7ae89ce9e8528c7b9baca3655b313843fa8a843cc3b28fd247"
    )
    assert (
        template.template_sha256
        == "cad86505c18298d465e932e6cae78f6344fa572c96ed39bc4df9504e6cb0acac"
    )
    store = PilotStore(tmp_path)
    store.save_check("owner", check)
    store.save_template("owner", template)

    application = CheckPilotApplication(tmp_path)
    batch = application.generate("owner", template.template_id, seed=42, quantity=3)

    assert batch.model_dump(mode="json") == {
        "template_id": template.template_id,
        "seed": 42,
        "questions": [
            {
                "question": "Differentiate p(x) = 3x^2 - 2x - 3 with respect to x.",
                "expression": "3x^2 - 2x - 3",
                "choices": ["6x - 2", "7x - 2", "5x - 2", "6x + 2"],
                "correct_index": 0,
                "answer": "6x - 2",
                "parameters": {
                    "a0": -3,
                    "a1": -2,
                    "a2": 3,
                    "degree": 2,
                    "variable": "x",
                },
                "check_ref": check.check_ref.model_dump(mode="json"),
                "engine_outcome": None,
                "kernel_verdict": None,
                "grader": "kernel",
            },
            {
                "question": "Differentiate p(x) = x^2 with respect to x.",
                "expression": "x^2",
                "choices": ["3x", "-2x", "2x - 1", "2x"],
                "correct_index": 3,
                "answer": "2x",
                "parameters": {
                    "a0": 0,
                    "a1": 0,
                    "a2": 1,
                    "degree": 2,
                    "variable": "x",
                },
                "check_ref": check.check_ref.model_dump(mode="json"),
                "engine_outcome": None,
                "kernel_verdict": None,
                "grader": "kernel",
            },
            {
                "question": "Differentiate p(x) = 3x^2 - 2x - 1 with respect to x.",
                "expression": "3x^2 - 2x - 1",
                "choices": [
                    "-x^2 + 6x - 2",
                    "x^2 + 6x - 2",
                    "6x^2 - 2x + 1",
                    "6x - 2",
                ],
                "correct_index": 3,
                "answer": "6x - 2",
                "parameters": {
                    "a0": -1,
                    "a1": -2,
                    "a2": 3,
                    "degree": 2,
                    "variable": "x",
                },
                "check_ref": check.check_ref.model_dump(mode="json"),
                "engine_outcome": None,
                "kernel_verdict": None,
                "grader": "kernel",
            },
        ],
        "requested_quantity": 3,
        "shortfall": 0,
        "findings": [],
    }
    # The additive v2 selection field is absent on old records.
    assert application.get_template("owner", template.template_id).selection is None
