"""Independent Hypothesis qualification of compiled derivative checks."""

from __future__ import annotations

import pytest
import sympy

from edcraft_validator.application.check_pilot.isolation import PilotWorkerTimeout
from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    PilotQualificationSettings,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.application.check_pilot.qualification import qualify_recipe


def input_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="input", name=name)


def step_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="step", name=name)


def literal_arg(value: int | bool) -> RecipeArgument:
    return RecipeArgument(source="literal", value=value)


def definition(*steps: RecipeStep) -> CheckRecipeDefinition:
    return CheckRecipeDefinition(steps=list(steps), output="out")


def differentiate(step_id: str = "d1", reference: str = "problem") -> RecipeStep:
    return RecipeStep(
        id=step_id,
        operation="poly.differentiate",
        version="1",
        arguments={"polynomial": input_arg(reference)},
    )


def differentiate_step(step_id: str, reference: str) -> RecipeStep:
    return RecipeStep(
        id=step_id,
        operation="poly.differentiate",
        version="1",
        arguments={"polynomial": step_arg(reference)},
    )


def equivalent(expected: RecipeArgument, actual: RecipeArgument) -> RecipeStep:
    return RecipeStep(
        id="out",
        operation="poly.equivalent",
        version="1",
        arguments={"expected": expected, "actual": actual},
    )


def valid_recipe() -> CheckRecipeDefinition:
    return definition(
        differentiate(), equivalent(step_arg("d1"), input_arg("candidate"))
    )


def settings(**changes) -> PilotQualificationSettings:
    values = {
        "max_examples": 20,
        "max_execution_calls": 600,
        "timeout_seconds": 30.0,
    }
    values.update(changes)
    return PilotQualificationSettings(**values)


def test_correct_recipe_passes_property_based_qualification():
    result = qualify_recipe(valid_recipe(), seed=17, settings=settings())
    assert result.status == "passed"
    assert result.phase == "sampling"
    assert result.checking_mode == "property_based"
    assert result.accepted_cases >= 10
    assert result.execution_calls > result.accepted_cases
    assert result.max_examples == 20
    assert result.max_execution_calls == 600
    assert result.timeout_seconds == 30.0
    assert result.seed == 17
    assert result.counterexample is None
    assert "No counterexample found in sampled cases" in result.findings
    assert result.versions["polynomial_oracle"] == "coefficient-arithmetic/1"
    assert result.versions["differentiation"] == "sympy"
    assert result.versions["sympy"] == sympy.__version__
    assert result.versions["hypothesis"]


def test_second_derivative_fails_with_preserved_shrunk_counterexample():
    wrong = definition(
        differentiate(),
        differentiate_step("d2", "d1"),
        equivalent(step_arg("d2"), input_arg("candidate")),
    )
    first = qualify_recipe(wrong, seed=5, settings=settings())
    second = qualify_recipe(wrong, seed=5, settings=settings())
    assert first.status == "failed"
    assert first.phase == "sampling"
    assert first.counterexample is not None
    assert first.counterexample == second.counterexample
    assert "expected" in first.counterexample
    assert "candidate" in first.counterexample
    assert len(str(first.counterexample)) < 2_000


def test_always_true_and_always_false_recipes_are_rejected():
    always_true = definition(
        differentiate(),
        RecipeStep(
            id="out",
            operation="verdict.constant",
            version="1",
            arguments={"value": literal_arg(True)},
        ),
    )
    always_false = definition(
        differentiate(),
        RecipeStep(
            id="out",
            operation="verdict.constant",
            version="1",
            arguments={"value": literal_arg(False)},
        ),
    )
    for recipe in (always_true, always_false):
        result = qualify_recipe(recipe, seed=1, settings=settings())
        assert result.status == "error"
        assert result.phase == "compilation"
        assert result.execution_calls == 0
        assert result.counterexample is None
        assert result.findings
        assert "verdict" in " ".join(result.findings).lower()


def test_candidate_to_itself_recipe_is_rejected():
    recipe = definition(
        differentiate(),
        equivalent(input_arg("candidate"), input_arg("candidate")),
    )
    result = qualify_recipe(recipe, seed=1, settings=settings())
    assert result.status == "error"
    assert result.phase == "compilation"
    assert result.execution_calls == 0
    assert result.counterexample is None
    assert result.findings


def test_small_point_only_check_is_not_sufficient():
    recipe = definition(
        differentiate(),
        RecipeStep(
            id="p1",
            operation="poly.evaluate_at",
            version="1",
            arguments={"polynomial": step_arg("d1"), "point": literal_arg(0)},
        ),
        RecipeStep(
            id="p2",
            operation="poly.evaluate_at",
            version="1",
            arguments={"polynomial": input_arg("candidate"), "point": literal_arg(0)},
        ),
        RecipeStep(
            id="out",
            operation="number.equal",
            version="1",
            arguments={"left": step_arg("p1"), "right": step_arg("p2")},
        ),
    )
    result = qualify_recipe(recipe, seed=2, settings=settings())
    assert result.status == "error"
    assert result.phase == "compilation"
    assert result.execution_calls == 0
    assert result.counterexample is None
    assert any("point" in finding.lower() for finding in result.findings)


def test_unknown_operation_is_a_development_needed_error_not_a_pass():
    recipe = definition(
        RecipeStep(
            id="d1",
            operation="poly.integrate",
            version="1",
            arguments={"polynomial": input_arg("problem")},
        ),
        equivalent(step_arg("d1"), input_arg("candidate")),
    )
    result = qualify_recipe(recipe, seed=1, settings=settings())
    assert result.status == "error"
    assert result.phase == "compilation"
    assert result.accepted_cases == 0
    assert result.execution_calls == 0
    assert result.counterexample is None
    assert any("development" in finding.lower() for finding in result.findings)


def test_budget_exhaustion_is_inconclusive_not_pass():
    result = qualify_recipe(
        valid_recipe(),
        seed=1,
        settings=settings(max_execution_calls=2, max_examples=20),
    )
    assert result.status == "inconclusive"
    assert any("budget" in finding.lower() for finding in result.findings)


def test_worker_failure_and_success_evidence_share_static_versions(
    monkeypatch: pytest.MonkeyPatch,
):
    success = qualify_recipe(valid_recipe(), seed=17, settings=settings())
    assert success.status == "passed"

    def timeout(*args, **kwargs):
        raise PilotWorkerTimeout("worker exceeded its hard limit")

    monkeypatch.setattr(
        "edcraft_validator.application.check_pilot.qualification.run_pilot_isolated",
        timeout,
    )
    failure = qualify_recipe(valid_recipe(), seed=17, settings=settings())

    assert failure.status == "error"
    assert "hard" in failure.findings[0]
    assert failure.versions
    assert failure.versions == {
        key: value for key, value in success.versions.items() if key in failure.versions
    }
    assert set(success.versions) - set(failure.versions) == {"hypothesis", "python"}
