"""Seeded question generation from an approved, fully pinned template."""

from __future__ import annotations

import random

from edcraft_validator.application.check_pilot.errors import (
    PilotConflict,
    PilotInputError,
)
from edcraft_validator.application.check_pilot.isolation import (
    PilotWorkerError,
    PilotWorkerTimeout,
)
from edcraft_validator.application.check_pilot.models import (
    MAX_RECIPE_CASES,
    CheckRecipeDefinition,
    PilotBatch,
    PilotQuestion,
    PilotTemplateDefinition,
)
from edcraft_validator.application.check_pilot.polynomial import parse_polynomial
from edcraft_validator.application.check_pilot.qualification import (
    execute_recipe_cases_isolated,
)
from edcraft_validator.application.check_pilot.question import (
    GeneratedInstance,
    QuestionBuildError,
    build_instance,
    guard_instance,
)
from edcraft_validator.application.check_pilot.storage import PilotStore

MAX_QUANTITY = 100
GENERATION_TIMEOUT_SECONDS = 15.0


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
    record = store.get_template(owner_id, template_id)
    if (
        record.status != "ready"
        or record.approval != "approved"
        or record.qualification is None
        or record.qualification.status != "passed"
        or record.check is None
        or record.template is None
    ):
        raise PilotConflict("the template must be ready and approved before generation")
    definition = PilotTemplateDefinition.model_validate(record.template)
    check = store.get_check(owner_id, record.check.check_ref.check_id)
    if check.check_ref.sha256 != record.check.check_ref.sha256:
        raise PilotConflict("the pinned check no longer matches this template")
    recipe = CheckRecipeDefinition.model_validate(check.definition)
    family = definition.family

    rng = random.Random(seed)
    seen: set[tuple[int, ...]] = set()
    instances: list[GeneratedInstance] = []
    skipped = 0
    max_attempts = max(50, quantity * 20)
    for attempt in range(max_attempts):
        if len(instances) >= quantity:
            break
        coefficients = tuple(
            rng.choice(domain.values) for domain in family.coefficients
        )
        if coefficients in seen:
            continue
        seen.add(coefficients)
        try:
            instance = build_instance(
                family,
                coefficients,
                seed=seed + attempt,
            )
        except QuestionBuildError:
            skipped += 1
            continue
        instances.append(instance)

    for instance in instances:
        guard_findings = guard_instance(
            instance, num_distractors=family.num_distractors
        )
        if guard_findings:
            raise PilotConflict(
                "a generated instance failed the independent correctness guard; "
                "no questions were returned"
            )

    cases = []
    for instance in instances:
        cases.append((instance.problem, instance.expected))
        for index, choice in enumerate(instance.choices):
            if index == instance.correct_index:
                continue
            cases.append((instance.problem, parse_polynomial(choice)))
    if len(cases) > MAX_RECIPE_CASES:
        raise PilotConflict(
            "the generated batch exceeds the bounded recipe-execution limit"
        )
    try:
        results = execute_recipe_cases_isolated(
            recipe, cases, timeout_seconds=timeout_seconds
        )
    except (PilotWorkerError, PilotWorkerTimeout, ValueError) as exc:
        raise PilotConflict(
            "the generated batch could not be checked safely; no questions "
            "were returned"
        ) from exc
    if len(results) != len(cases):
        raise PilotConflict("the pinned check returned an incomplete batch")
    cursor = 0
    for instance in instances:
        correct = results[cursor]
        cursor += 1
        if not correct.verdict:
            raise PilotConflict("the pinned check rejected a generated correct answer")
        for index in range(len(instance.choices)):
            if index == instance.correct_index:
                continue
            result = results[cursor]
            cursor += 1
            if result.verdict:
                raise PilotConflict(
                    "the pinned check accepted a generated distractor; no "
                    "questions were returned"
                )

    questions = [
        PilotQuestion(
            question=instance.question,
            expression=instance.expression,
            choices=list(instance.choices),
            correct_index=instance.correct_index,
            answer=instance.answer,
            parameters=instance.parameters,
            check_ref=check.check_ref,
        )
        for instance in instances
    ]
    shortfall = quantity - len(questions)
    findings: list[str] = []
    if skipped:
        findings.append(
            f"Skipped {skipped} sampled assignment(s) that could not be rendered "
            "safely."
        )
    if shortfall:
        findings.append(
            f"Generated {len(questions)} unique instance(s) for requested "
            f"{quantity} after bounded sampling. No claim is made about "
            "untested parts of the declared coefficient domains."
        )
    return PilotBatch(
        template_id=record.template_id,
        seed=seed,
        questions=questions,
        requested_quantity=quantity,
        shortfall=shortfall,
        findings=findings,
    )


__all__ = ["GENERATION_TIMEOUT_SECONDS", "MAX_QUANTITY", "generate_batch"]
