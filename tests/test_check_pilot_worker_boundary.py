"""Regression coverage for the pilot worker's trust and parsing boundary."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from hypothesis import given
from hypothesis import settings as hypothesis_settings

import edcraft_validator.application.check_pilot.operations as operations_module
from edcraft_validator.application.check_pilot.contracts import (
    scope_from_recipe_operation_set,
)
from edcraft_validator.application.check_pilot.kernel_registry import kernel_contract
from edcraft_validator.application.check_pilot.models import (
    SUPPORTED_SCOPE,
    CheckRecipeDefinition,
    PilotQualificationSettings,
    PolynomialScope,
    RecipeArgument,
    RecipeStep,
)
from edcraft_validator.application.check_pilot.operations import (
    compile_recipe,
    operation_catalogue,
)
from edcraft_validator.application.check_pilot.polynomial import Polynomial
from edcraft_validator.application.check_pilot.qualification import qualify_recipe
from edcraft_validator.application.check_pilot.worker import (
    _boundary_polynomials,
    _polynomial_strategy,
)
from edcraft_validator.mcp.server import create_validation_server


def input_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="input", name=name)


def step_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="step", name=name)


def derivative_recipe() -> dict[str, Any]:
    return {
        "steps": [
            {
                "id": "d1",
                "operation": "poly.differentiate",
                "version": "1",
                "arguments": {"polynomial": {"source": "input", "name": "problem"}},
            },
            {
                "id": "out",
                "operation": "poly.equivalent",
                "version": "1",
                "arguments": {
                    "expected": {"source": "step", "name": "d1"},
                    "actual": {"source": "input", "name": "candidate"},
                },
            },
        ],
        "output": "out",
    }


def solve_recipe() -> dict[str, Any]:
    return {
        "operation_set": "polynomial-solve-real/1",
        "steps": [
            {
                "id": "s1",
                "operation": "relation.solve_real",
                "version": "1",
                "arguments": {"problem": {"source": "input", "name": "problem"}},
            },
            {
                "id": "out",
                "operation": "set.equal",
                "version": "1",
                "arguments": {
                    "expected": {"source": "step", "name": "s1"},
                    "actual": {"source": "input", "name": "candidate"},
                },
            },
        ],
        "output": "out",
    }


def structured_recipe() -> dict[str, Any]:
    return {
        "operation_set": "structured-check/1",
        "steps": [
            {
                "id": "e1",
                "operation": "structured.expected",
                "version": "1",
                "arguments": {"problem": {"source": "input", "name": "problem"}},
            },
            {
                "id": "out",
                "operation": "structured.accepts",
                "version": "1",
                "arguments": {
                    "expected": {"source": "step", "name": "e1"},
                    "problem": {"source": "input", "name": "problem"},
                    "candidate": {"source": "input", "name": "candidate"},
                },
            },
        ],
        "output": "out",
    }


def valid_recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        steps=[
            RecipeStep(
                id="d1",
                operation="poly.differentiate",
                version="1",
                arguments={"polynomial": input_arg("problem")},
            ),
            RecipeStep(
                id="out",
                operation="poly.equivalent",
                version="1",
                arguments={
                    "expected": step_arg("d1"),
                    "actual": input_arg("candidate"),
                },
            ),
        ],
        output="out",
    )


def qualification_settings(**changes: object) -> PilotQualificationSettings:
    values: dict[str, object] = {
        "max_examples": 20,
        "max_execution_calls": 600,
        "timeout_seconds": 30.0,
    }
    values.update(changes)
    return PilotQualificationSettings(**values)


async def call_tool(
    server: Any, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    async with Client(server) as client:
        result = await client.call_tool(name, arguments)
    assert not result.is_error
    assert result.structured_content is not None
    return result.structured_content


async def test_mcp_execution_does_not_run_host_symbolic_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("host symbolic validation ran on the MCP side")

    monkeypatch.setattr(
        operations_module, "validate_execution_inputs", forbidden, raising=False
    )

    result = await call_tool(
        create_validation_server(),
        "check_pilot_execute_recipe",
        {
            "definition": derivative_recipe(),
            "problem": "3*x^2 - 2*x + 1",
            "candidate": "6*x - 2",
        },
    )

    assert result["status"] == "passed"
    assert result["details"]["verdict"] is True


async def test_malformed_structured_candidate_is_recipe_invalid() -> None:
    problem = {
        "kind": "matrix_determinant",
        "matrix": [["1", "2"], ["3", "4"]],
    }
    result = await call_tool(
        create_validation_server(),
        "check_pilot_execute_recipe",
        {
            "definition": structured_recipe(),
            "problem": problem,
            "candidate": "not-an-object",
            "contract_id": "matrix.determinant/1",
        },
    )

    assert result["status"] == "error"
    assert result["findings"][0]["code"] == "RECIPE_INVALID"


def test_qualification_rejects_a_payload_scope_above_the_trusted_bound() -> None:
    result = qualify_recipe(
        valid_recipe(),
        seed=17,
        settings=qualification_settings(),
        scope=PolynomialScope(max_abs_coefficient=1000),
    )

    assert result.status == "error"
    assert some_finding_mentions(result.findings, "scope")


def test_qualification_accepts_a_scope_narrower_than_the_trusted_bound() -> None:
    result = qualify_recipe(
        valid_recipe(),
        seed=17,
        settings=qualification_settings(),
        scope=PolynomialScope(max_degree=2, max_abs_coefficient=3),
    )

    assert result.status == "passed"
    assert result.accepted_cases >= 2


def test_differentiation_sampling_stays_inside_the_supplied_scope() -> None:
    scope = PolynomialScope(max_degree=2, max_abs_coefficient=3)

    @given(_polynomial_strategy(scope))
    @hypothesis_settings(max_examples=40, deadline=None, database=None)
    def sampled(polynomial: Polynomial) -> None:
        assert polynomial.degree <= scope.max_degree
        assert all(
            abs(coefficient) <= scope.max_abs_coefficient
            for coefficient in polynomial.coefficients
        )

    sampled()
    for polynomial in _boundary_polynomials(scope):
        assert polynomial.degree <= scope.max_degree
        assert all(
            abs(coefficient) <= scope.max_abs_coefficient
            for coefficient in polynomial.coefficients
        )


def test_catalogue_advertises_only_operations_that_compile() -> None:
    catalogue = operation_catalogue()
    advertised = {entry["id"] for entry in catalogue}
    weak = {
        "poly.identity",
        "poly.evaluate_at",
        "number.equal",
        "verdict.constant",
    }
    assert advertised.isdisjoint(weak)

    derivative = CheckRecipeDefinition.model_validate(derivative_recipe())
    solve = CheckRecipeDefinition.model_validate(solve_recipe())
    structured = CheckRecipeDefinition.model_validate(structured_recipe())
    contract = kernel_contract("matrix.determinant/1")
    assert contract is not None

    compile_recipe(derivative, scope=SUPPORTED_SCOPE)
    compile_recipe(
        solve,
        scope=scope_from_recipe_operation_set("polynomial-solve-real/1"),
    )
    compile_recipe(structured, scope=contract.scope())

    compiled_operations = {
        step.operation
        for recipe in (derivative, solve, structured)
        for step in recipe.steps
    }
    assert advertised == compiled_operations


async def test_mcp_polynomial_text_boundary_is_200_characters() -> None:
    server = create_validation_server()
    accepted = await call_tool(
        server,
        "check_pilot_execute_recipe",
        {
            "definition": derivative_recipe(),
            "problem": "x" + " " * 199,
            "candidate": "1",
        },
    )
    assert accepted["status"] == "passed"

    rejected = await call_tool(
        server,
        "check_pilot_execute_recipe",
        {
            "definition": derivative_recipe(),
            "problem": "x" + " " * 200,
            "candidate": "1",
        },
    )
    assert rejected["status"] == "error"
    assert rejected["findings"][0]["code"] == "RECIPE_INVALID"
    assert "200" in rejected["findings"][0]["message"]


def some_finding_mentions(findings: list[str], text: str) -> bool:
    return any(text in finding.lower() for finding in findings)
