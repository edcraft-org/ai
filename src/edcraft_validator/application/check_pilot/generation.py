"""Seeded generation from an approved, fully pinned template.

This module deliberately owns no symbolic generation logic. It validates the
owner's stored template/check/approval/hash/applicability evidence and sends one
closed request to the disposable pilot worker, which performs sampling,
rendering, guarding, recipe compilation and every recipe verdict in one process.
"""

from __future__ import annotations

import math

from edcraft_validator.application.check_pilot.contracts import (
    scope_applicability_findings,
    template_goal,
)
from edcraft_validator.application.check_pilot.errors import (
    PilotConflict,
    PilotInputError,
)
from edcraft_validator.application.check_pilot.isolation import (
    PilotWorkerError,
    PilotWorkerTimeout,
    run_pilot_isolated,
)
from edcraft_validator.application.check_pilot.models import (
    MAX_GENERATION_QUANTITY,
    CheckRecipeDefinition,
    EngineCheckDefinition,
    EngineContractScope,
    PilotBatch,
    PilotTemplateDefinition,
)
from edcraft_validator.application.check_pilot.storage import (
    PilotStore,
    template_definition_sha256,
)

MAX_QUANTITY = MAX_GENERATION_QUANTITY
GENERATION_TIMEOUT_SECONDS = 45.0


def generate_batch(
    store: PilotStore,
    owner_id: str,
    template_id: str,
    *,
    seed: int,
    quantity: int,
    timeout_seconds: float = GENERATION_TIMEOUT_SECONDS,
) -> PilotBatch:
    if type(seed) is not int or seed < 0:
        raise PilotInputError("generation seed must be a non-negative integer")
    if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
        raise PilotInputError(f"quantity must be between 1 and {MAX_QUANTITY}")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise PilotInputError("generation timeout must be finite and positive")

    record = store.get_template(owner_id, template_id)
    record_check = record.check
    if (
        record.status != "ready"
        or record.approval != "approved"
        or record.qualification is None
        or record.qualification.status != "passed"
        or record_check is None
        or record.template is None
    ):
        raise PilotConflict("the template must be ready and approved before generation")

    definition = PilotTemplateDefinition.model_validate(record.template)
    if template_definition_sha256(definition) != record.template_sha256:
        raise PilotConflict("the template changed; no questions were returned")
    check = store.get_check(owner_id, record_check.check_ref.check_id)
    if check.check_ref != record_check.check_ref:
        raise PilotConflict("the pinned check no longer matches this template")
    if scope_applicability_findings(check.scope, template_goal(definition)):
        raise PilotConflict("the pinned check does not cover this template")

    if isinstance(definition.scope, EngineContractScope):
        engine_definition: CheckRecipeDefinition | EngineCheckDefinition = (
            EngineCheckDefinition.model_validate(check.definition)
        )
    else:
        engine_definition = CheckRecipeDefinition.model_validate(check.definition)

    try:
        response = run_pilot_isolated(
            {
                "operation": "generate_batch",
                "template_id": record.template_id,
                "seed": seed,
                "quantity": quantity,
                "definition": engine_definition.model_dump(mode="json"),
                "template": definition.model_dump(mode="json", exclude_none=True),
                "check_ref": check.check_ref.model_dump(mode="json"),
            },
            timeout_seconds=timeout_seconds,
        )
    except PilotWorkerTimeout as exc:
        raise PilotConflict(
            "the generation worker exceeded its hard time limit; no questions "
            "were returned"
        ) from exc
    except (PilotWorkerError, ValueError, KeyError) as exc:
        raise PilotConflict(
            "the generated batch could not be checked safely; no questions "
            "were returned"
        ) from exc

    raw_batch = response.get("batch")
    if not isinstance(raw_batch, dict):
        raise PilotConflict(
            "the generation worker returned no complete batch; no questions "
            "were returned"
        )
    try:
        batch = PilotBatch.model_validate(raw_batch)
    except (TypeError, ValueError) as exc:
        raise PilotConflict(
            "the generation worker returned an invalid batch; no questions "
            "were returned"
        ) from exc
    if (
        batch.template_id != record.template_id
        or batch.seed != seed
        or batch.requested_quantity != quantity
        or len(batch.questions) > quantity
        or batch.shortfall != quantity - len(batch.questions)
        or any(question.check_ref != check.check_ref for question in batch.questions)
    ):
        raise PilotConflict(
            "the generation worker returned a mismatched batch; no questions "
            "were returned"
        )
    return batch


__all__ = ["GENERATION_TIMEOUT_SECONDS", "MAX_QUANTITY", "generate_batch"]
