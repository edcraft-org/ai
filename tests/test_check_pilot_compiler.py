"""Trusted polynomial arithmetic and compiled recipe validation for the pilot."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from edcraft_validator.application.check_pilot.models import (
    CheckRecipeDefinition,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.application.check_pilot.operations import (
    RecipeCompileError,
    compile_recipe,
    execute_recipe,
    operation_catalogue,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    derivative_via_coefficients,
    parse_polynomial,
    render_polynomial,
)


def input_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="input", name=name)


def step_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="step", name=name)


def literal_arg(value: int | bool) -> RecipeArgument:
    return RecipeArgument(source="literal", value=value)


def recipe(*steps: RecipeStep, output: str = "out") -> CheckRecipeDefinition:
    return CheckRecipeDefinition(steps=list(steps), output=output)


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


def test_polynomial_parser_accepts_alternate_forms_and_rejects_code():
    expected = Polynomial.from_coefficients([1, -2, 0, 3])
    for text in (
        "3x^3 - 2x + 1",
        "3*x^3 - 2*x + 1",
        "1 - 2*x + 3*x^3",
        "(3x^3 - 2x + 1)",
        "3x^3 - 2x + 1 + 0x^2",
    ):
        assert parse_polynomial(text) == expected
    assert render_polynomial(expected) == "3x^3 - 2x + 1"
    for text in ("__import__('os')", "x/2", "x^9", "2.5x", "x**2", ""):
        with pytest.raises(ValueError):
            parse_polynomial(text)


def test_independent_derivative_uses_coefficient_arithmetic():
    problem = Polynomial.from_coefficients([7, -2, 0, 3])
    assert derivative_via_coefficients(problem) == Polynomial.from_coefficients(
        [-2, 0, 9]
    )
    assert derivative_via_coefficients(Polynomial.from_coefficients([5])) == (
        Polynomial.from_coefficients([0])
    )


def test_operation_catalogue_is_typed_and_versioned():
    catalogue = operation_catalogue()
    assert {entry["id"] for entry in catalogue} >= {
        "poly.differentiate",
        "poly.equivalent",
        "poly.evaluate_at",
        "number.equal",
        "verdict.constant",
    }
    for entry in catalogue:
        assert entry["version"] == "1"
        assert entry["inputs"]
        assert entry["output"]
        assert entry["summary"]


def test_valid_recipe_compiles_and_executes_against_candidates():
    compiled = compile_recipe(
        recipe(differentiate(), equivalent(step_arg("d1"), input_arg("candidate")))
    )
    problem = parse_polynomial("3x^3 - 2x + 1")
    assert execute_recipe(compiled, problem, parse_polynomial("9x^2 - 2")).verdict
    assert not execute_recipe(compiled, problem, parse_polynomial("9x^2 + 2")).verdict
    assert compiled.expected_step_id == "d1"


def test_compiler_checks_refs_ids_types_and_capabilities():
    with pytest.raises(RecipeCompileError) as unknown:
        compile_recipe(
            recipe(
                RecipeStep(
                    id="d1",
                    operation="poly.magic",
                    version="1",
                    arguments={"polynomial": input_arg("problem")},
                ),
                equivalent(step_arg("d1"), input_arg("candidate")),
            )
        )
    assert unknown.value.unknown_capability

    with pytest.raises(RecipeCompileError, match="duplicate"):
        compile_recipe(
            recipe(
                differentiate("d1"),
                differentiate("d1"),
                equivalent(step_arg("d1"), input_arg("candidate")),
            )
        )

    with pytest.raises(RecipeCompileError, match="forward|prior"):
        compile_recipe(
            recipe(
                RecipeStep(
                    id="d1",
                    operation="poly.differentiate",
                    version="1",
                    arguments={"polynomial": step_arg("later")},
                ),
                differentiate("later"),
                equivalent(step_arg("d1"), input_arg("candidate")),
            )
        )

    with pytest.raises(RecipeCompileError, match="argument"):
        compile_recipe(
            recipe(
                differentiate(),
                RecipeStep(
                    id="out",
                    operation="poly.equivalent",
                    version="1",
                    arguments={"expected": step_arg("d1")},
                ),
            )
        )

    with pytest.raises(RecipeCompileError, match="literal"):
        compile_recipe(
            recipe(
                differentiate(),
                RecipeStep(
                    id="out",
                    operation="poly.equivalent",
                    version="1",
                    arguments={
                        "expected": literal_arg(True),
                        "actual": input_arg("candidate"),
                    },
                ),
            )
        )

    with pytest.raises(ValidationError):
        CheckRecipeDefinition(steps=[], output="out")

    with pytest.raises(ValidationError):
        RecipeStep(
            id="bad id",
            operation="poly.differentiate",
            version="1",
            arguments={"polynomial": input_arg("problem")},
        )


def test_compiler_rejects_constant_verdicts():
    with pytest.raises(RecipeCompileError, match="differentiate"):
        compile_recipe(
            recipe(
                differentiate(),
                RecipeStep(
                    id="out",
                    operation="verdict.constant",
                    version="1",
                    arguments={"value": literal_arg(True)},
                ),
            )
        )


def test_compiler_accepts_structurally_valid_but_semantically_wrong_recipe():
    # A second derivative is well-typed; independent qualification, not the
    # compiler, must reject it as the wrong mathematical operation.
    compile_recipe(
        recipe(
            differentiate(),
            differentiate_step("d2", "d1"),
            equivalent(step_arg("d2"), input_arg("candidate")),
        )
    )


def test_compiler_rejects_always_true_false_and_candidate_to_itself():
    always_true = recipe(
        differentiate(),
        RecipeStep(
            id="out",
            operation="verdict.constant",
            version="1",
            arguments={"value": literal_arg(True)},
        ),
    )
    always_false = recipe(
        differentiate(),
        RecipeStep(
            id="out",
            operation="verdict.constant",
            version="1",
            arguments={"value": literal_arg(False)},
        ),
    )
    itself = recipe(
        differentiate(),
        equivalent(input_arg("candidate"), input_arg("candidate")),
    )
    point_only = recipe(
        differentiate(),
        RecipeStep(
            id="p1",
            operation="poly.evaluate_at",
            version="1",
            arguments={
                "polynomial": step_arg("d1"),
                "point": literal_arg(0),
            },
        ),
        RecipeStep(
            id="p2",
            operation="poly.evaluate_at",
            version="1",
            arguments={
                "polynomial": input_arg("candidate"),
                "point": literal_arg(0),
            },
        ),
        RecipeStep(
            id="out",
            operation="number.equal",
            version="1",
            arguments={"left": step_arg("p1"), "right": step_arg("p2")},
        ),
    )
    for definition in (always_true, always_false, itself, point_only):
        with pytest.raises(RecipeCompileError):
            compile_recipe(definition)
