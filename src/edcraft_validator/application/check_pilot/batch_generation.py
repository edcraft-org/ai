"""Single deterministic batch-generation algorithm, executed inside the worker.

The application process only validates owner storage, approval, hashes and
contract applicability. Sampling, symbolic rendering/guarding, recipe
compilation and every recipe verdict run here in one disposable interpreter, so
no new polynomial/solution-set/kernel arithmetic reaches the application host.
"""

from __future__ import annotations

import json
import random

from edcraft_validator.application.check_pilot.models import (
    MAX_GENERATION_QUANTITY,
    MAX_RECIPE_CASES,
    CheckRecipeDefinition,
    CheckRef,
    ContractScope,
    KernelContractScope,
    KernelGoal,
    PilotBatch,
    PilotQuestion,
    PilotTemplateDefinition,
    PolynomialFamily,
    PolynomialScope,
    SolveFamily,
    StructuredProblemFamily,
)
from edcraft_validator.application.check_pilot.operations import (
    CompiledRecipe,
    RecipeCompileError,
    compile_recipe,
    execute_recipe,
)
from edcraft_validator.application.check_pilot.polynomial import (
    parse_polynomial,
)
from edcraft_validator.application.check_pilot.question import (
    GeneratedInstance,
    QuestionBuildError,
    SolveGeneratedInstance,
    build_instance,
    build_solve_instance,
    guard_instance,
    guard_solve_instance,
)
from edcraft_validator.application.check_pilot.solution_sets import (
    solution_set_model,
)
from edcraft_validator.application.check_pilot.structured import (
    StructuredFamilyError,
    StructuredGeneratedInstance,
    problem_goal_findings,
    sampled_assignments,
)
from edcraft_validator.application.check_pilot.structured import (
    build_instance as build_structured_instance,
)
from edcraft_validator.application.check_pilot.structured import (
    guard_instance as guard_structured_instance,
)

Generated = GeneratedInstance | SolveGeneratedInstance | StructuredGeneratedInstance
Family = PolynomialFamily | SolveFamily | StructuredProblemFamily


class BatchGenerationError(RuntimeError):
    """The validated request cannot produce a complete, safe batch."""


def _family(definition: PilotTemplateDefinition) -> Family:
    if definition.structured_family is not None:
        return definition.structured_family
    if definition.solve_family is not None:
        return definition.solve_family
    if definition.family is None:
        raise BatchGenerationError("the template declares no generation family")
    return definition.family


def _sample_structured_instances(
    family: StructuredProblemFamily,
    *,
    seed: int,
    quantity: int,
) -> tuple[list[Generated], int]:
    instances: list[Generated] = []
    seen: set[str] = set()
    skipped = 0
    assignments = sampled_assignments(
        family, seed=seed, limit=max(quantity * 4, quantity)
    )
    for attempt, assignment in enumerate(assignments):
        if len(instances) >= quantity:
            break
        try:
            instance = build_structured_instance(
                family, assignment, seed=seed + attempt
            )
        except (StructuredFamilyError, ValueError):
            skipped += 1
            continue
        marker = json.dumps(instance.problem, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        instances.append(instance)
    return instances, skipped


def _sample_instances(
    family: Family,
    *,
    seed: int,
    quantity: int,
) -> tuple[list[Generated], int]:
    if isinstance(family, StructuredProblemFamily):
        return _sample_structured_instances(family, seed=seed, quantity=quantity)
    rng = random.Random(seed)
    seen: set[tuple[int, ...]] = set()
    instances: list[Generated] = []
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
            if isinstance(family, SolveFamily):
                instance: Generated = build_solve_instance(
                    family, coefficients, seed=seed + attempt
                )
            else:
                instance = build_instance(family, coefficients, seed=seed + attempt)
        except QuestionBuildError:
            skipped += 1
            continue
        instances.append(instance)
    return instances, skipped


def _guard(
    instance: Generated,
    *,
    family: Family,
    scope: PolynomialScope | ContractScope | KernelContractScope,
    goal: KernelGoal | None,
) -> list[str]:
    if isinstance(instance, StructuredGeneratedInstance):
        if not isinstance(family, StructuredProblemFamily) or not isinstance(
            scope, KernelContractScope
        ):
            return ["structured instance has no kernel family and scope"]
        findings = guard_structured_instance(
            instance,
            contract_id=family.contract_id,
            num_distractors=family.num_distractors,
            scope=scope,
        )
        if findings:
            return findings
        if goal is None:
            return ["structured instance has no validated goal"]
        return problem_goal_findings(
            family.contract_id,
            goal,
            instance.problem,
        )
    if isinstance(instance, SolveGeneratedInstance):
        return guard_solve_instance(instance, num_distractors=family.num_distractors)
    return guard_instance(instance, num_distractors=family.num_distractors)


def _recipe_cases(
    instance: Generated,
) -> list[tuple[object, object]]:
    if isinstance(instance, StructuredGeneratedInstance):
        cases: list[tuple[object, object]] = [(instance.problem, instance.expected)]
        cases.extend(
            (instance.problem, distractor) for distractor in instance.distractors
        )
        return cases
    if isinstance(instance, SolveGeneratedInstance):
        solution_cases: list[tuple[object, object]] = [
            (instance.relation, solution_set_model(instance.expected))
        ]
        solution_cases.extend(
            (instance.relation, solution_set_model(distractor))
            for distractor in instance.distractors
        )
        return solution_cases
    cases = [(instance.problem, instance.expected)]
    for index, choice in enumerate(instance.choices):
        if index == instance.correct_index:
            continue
        cases.append((instance.problem, parse_polynomial(choice)))
    return cases


def _check_verdicts(
    compiled: CompiledRecipe,
    instances: list[Generated],
) -> None:
    for instance in instances:
        cases = _recipe_cases(instance)
        correct = execute_recipe(compiled, cases[0][0], cases[0][1])
        if not correct.verdict:
            raise BatchGenerationError(
                "the pinned check rejected a generated correct answer"
            )
        for problem, candidate in cases[1:]:
            result = execute_recipe(compiled, problem, candidate)
            if result.verdict:
                raise BatchGenerationError(
                    "the pinned check accepted a generated distractor; no "
                    "questions were returned"
                )


def generate_batch(
    *,
    template_id: str,
    seed: int,
    quantity: int,
    definition: CheckRecipeDefinition,
    template: PilotTemplateDefinition,
    check_ref: CheckRef,
) -> PilotBatch:
    """Create one complete batch from already validated closed inputs."""
    if type(seed) is not int or seed < 0:
        raise BatchGenerationError("generation seed must be a non-negative integer")
    if type(quantity) is not int or not 1 <= quantity <= MAX_GENERATION_QUANTITY:
        raise BatchGenerationError(
            f"quantity must be between 1 and {MAX_GENERATION_QUANTITY}"
        )
    if not isinstance(template_id, str) or not template_id:
        raise BatchGenerationError("template id is required")

    family = _family(template)
    try:
        compiled = compile_recipe(definition, scope=template.scope)
    except RecipeCompileError as exc:
        raise BatchGenerationError(
            f"the pinned check did not compile: {'; '.join(exc.findings)[:500]}"
        ) from None

    instances, skipped = _sample_instances(family, seed=seed, quantity=quantity)
    for instance in instances:
        if _guard(
            instance,
            family=family,
            scope=template.scope,
            goal=template.goal,
        ):
            raise BatchGenerationError(
                "a generated instance failed the independent correctness guard; "
                "no questions were returned"
            )

    case_count = sum(len(instance.choices) for instance in instances)
    if case_count > MAX_RECIPE_CASES:
        raise BatchGenerationError(
            "the generated batch exceeds the bounded recipe-execution limit"
        )
    try:
        _check_verdicts(compiled, instances)
    except RecipeCompileError as exc:
        raise BatchGenerationError(
            f"the pinned check failed during execution: {'; '.join(exc.findings)[:500]}"
        ) from None

    questions = [
        PilotQuestion(
            question=instance.question,
            expression=instance.expression,
            choices=list(instance.choices),
            correct_index=instance.correct_index,
            answer=instance.answer,
            parameters=instance.parameters,
            check_ref=check_ref,
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
            "untested parts of the declared parameter domains."
        )
    return PilotBatch(
        template_id=template_id,
        seed=seed,
        questions=questions,
        requested_quantity=quantity,
        shortfall=shortfall,
        findings=findings,
    )


__all__ = ["BatchGenerationError", "generate_batch"]
