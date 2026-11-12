"""Application-side entry points for isolated qualification and execution."""

from __future__ import annotations

import hashlib
import math
from importlib.metadata import version as package_version
from typing import Any

from edcraft_validator.application.check_pilot.isolation import (
    PilotWorkerError,
    PilotWorkerTimeout,
    run_pilot_isolated,
)
from edcraft_validator.application.check_pilot.models import (
    MAX_RECIPE_CASES,
    RENDERER_VERSION,
    SOLVE_RENDERER_VERSION,
    CheckRecipeDefinition,
    ContractScope,
    PilotQualificationSettings,
    PilotTemplateDefinition,
    PolynomialRelation,
    PolynomialScope,
    Qualification,
    RealSolutionSet,
    RecipeExecutionResult,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    render_polynomial,
)


def _static_versions() -> dict[str, str]:
    return {
        "check_pilot": "1",
        "differentiation": "sympy",
        "sympy": package_version("sympy"),
        "oracle": "coefficient-arithmetic/1",
        "polynomial_oracle": "coefficient-arithmetic/1",
        "solution_oracle": "discriminant-sign/1",
        "recipe_compiler": "1",
        "renderer": RENDERER_VERSION,
        "solve_renderer": SOLVE_RENDERER_VERSION,
        "question_builder": RENDERER_VERSION,
        "solve_question_builder": SOLVE_RENDERER_VERSION,
    }


def _worker_failure(
    *,
    seed: int,
    settings: PilotQualificationSettings,
    message: str,
) -> Qualification:
    return Qualification(
        status="error",
        accepted_cases=0,
        execution_calls=0,
        seed=seed,
        max_examples=settings.max_examples,
        max_execution_calls=settings.max_execution_calls,
        timeout_seconds=settings.timeout_seconds,
        counterexample=None,
        findings=[message],
        versions=_static_versions(),
    )


def _seed(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("qualification seed must be a non-negative integer")
    return value


def _run_qualification(
    payload: dict[str, Any],
    *,
    seed: int,
    settings: PilotQualificationSettings,
) -> Qualification:
    try:
        response = run_pilot_isolated(payload, timeout_seconds=settings.timeout_seconds)
        return Qualification.model_validate(response["qualification"])
    except PilotWorkerTimeout:
        return _worker_failure(
            seed=seed,
            settings=settings,
            message="qualification worker exceeded its hard time limit",
        )
    except (PilotWorkerError, KeyError, ValueError) as exc:
        return _worker_failure(
            seed=seed,
            settings=settings,
            message=(
                "qualification worker failed safely: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            ),
        )


def qualify_recipe(
    definition: CheckRecipeDefinition,
    *,
    seed: int,
    settings: PilotQualificationSettings | None = None,
    scope: PolynomialScope | ContractScope | None = None,
) -> Qualification:
    """Qualify a check recipe against an independent coefficient oracle."""
    selected = settings or PilotQualificationSettings()
    seed_value = _seed(seed)
    payload: dict[str, Any] = {
        "operation": "qualify_recipe",
        "definition": definition.model_dump(mode="json"),
        "seed": seed_value,
        "settings": selected.model_dump(mode="json"),
    }
    if scope is not None:
        payload["scope"] = scope.model_dump(mode="json")
    return _run_qualification(
        payload,
        seed=seed_value,
        settings=selected,
    )


def qualify_template(
    definition: CheckRecipeDefinition,
    family: Any,
    *,
    seed: int,
    settings: PilotQualificationSettings | None = None,
    scope: PolynomialScope | ContractScope | None = None,
) -> Qualification:
    """Qualify a reusable family separately from check qualification."""
    selected = settings or PilotQualificationSettings()
    seed_value = _seed(seed)
    payload: dict[str, Any] = {
        "operation": "qualify_template",
        "definition": definition.model_dump(mode="json"),
        "family": family.model_dump(mode="json"),
        "seed": seed_value,
        "settings": selected.model_dump(mode="json"),
    }
    if scope is not None:
        payload["scope"] = scope.model_dump(mode="json")
    return _run_qualification(
        payload,
        seed=seed_value,
        settings=selected,
    )


def qualify_structured_template(
    definition: CheckRecipeDefinition,
    template: PilotTemplateDefinition,
    *,
    seed: int,
    settings: PilotQualificationSettings | None = None,
) -> Qualification:
    """Qualify a version-2 structured template with its pinned contract."""
    selected = settings or PilotQualificationSettings()
    seed_value = _seed(seed)
    payload = {
        "operation": "qualify_template",
        "definition": definition.model_dump(mode="json"),
        "template": template.model_dump(mode="json", exclude_none=True),
        "seed": seed_value,
        "settings": selected.model_dump(mode="json"),
    }
    return _run_qualification(
        payload,
        seed=seed_value,
        settings=selected,
    )


def _serialize_problem(problem: Polynomial | PolynomialRelation) -> dict[str, Any]:
    if isinstance(problem, PolynomialRelation):
        return {"kind": "relation", "relation": problem.model_dump(mode="json")}
    return {"kind": "polynomial", "text": render_polynomial(problem)}


def _serialize_candidate(
    candidate: Polynomial | RealSolutionSet,
) -> dict[str, Any]:
    if isinstance(candidate, RealSolutionSet):
        return {
            "kind": "solution_set",
            "solution_set": candidate.model_dump(mode="json"),
        }
    return {"kind": "polynomial", "text": render_polynomial(candidate)}


def execute_recipe_isolated(
    definition: CheckRecipeDefinition,
    problem: Polynomial | PolynomialRelation,
    candidate: Polynomial | RealSolutionSet,
    *,
    timeout_seconds: float = 10.0,
) -> RecipeExecutionResult:
    """Run the same validated recipe implementation used by the pilot."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("recipe timeout must be finite and positive")
    response = run_pilot_isolated(
        {
            "operation": "execute_recipe",
            "definition": definition.model_dump(mode="json"),
            "problem": _serialize_problem(problem),
            "candidate": _serialize_candidate(candidate),
        },
        timeout_seconds=timeout_seconds,
    )
    return RecipeExecutionResult.model_validate(response["result"])


def execute_recipe_cases_isolated(
    definition: CheckRecipeDefinition,
    cases: list[tuple[Polynomial | PolynomialRelation, Polynomial | RealSolutionSet]],
    *,
    timeout_seconds: float = 10.0,
) -> list[RecipeExecutionResult]:
    """Validate one generated batch in a single disposable interpreter."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("recipe timeout must be finite and positive")
    if len(cases) > MAX_RECIPE_CASES:
        raise ValueError(f"a batch may contain at most {MAX_RECIPE_CASES} recipe cases")
    response = run_pilot_isolated(
        {
            "operation": "execute_recipe_cases",
            "definition": definition.model_dump(mode="json"),
            "cases": [
                {
                    "problem": _serialize_problem(problem),
                    "candidate": _serialize_candidate(candidate),
                }
                for problem, candidate in cases
            ],
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.get("results")
    if not isinstance(payload, list):
        raise PilotWorkerError("pilot worker returned no recipe results")
    return [RecipeExecutionResult.model_validate(item) for item in payload]


def qualification_seed(*parts: str) -> int:
    """Stable non-negative seed from content identity."""
    digest = hashlib.sha256("\0".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF


__all__ = [
    "PilotWorkerError",
    "PilotWorkerTimeout",
    "execute_recipe_cases_isolated",
    "execute_recipe_isolated",
    "qualification_seed",
    "qualify_recipe",
    "qualify_structured_template",
    "qualify_template",
]
