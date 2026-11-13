"""Bounded property-based qualification of parameterised correctness requests.

This module samples inputs, never authors recipes and never enumerates products.
It is run inside the same disposable process as symbolic checking.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import hypothesis
import sympy
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st
from pydantic import Field, model_validator

from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest, Record
from edcraft_validator.domains.math.engine.dispatch import check_in_process
from edcraft_validator.domains.math.engine.validation import bounded_number


class SampleParameter(Record):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    minimum: int | None = Field(default=None, ge=-1000000, le=1000000)
    maximum: int | None = Field(default=None, ge=-1000000, le=1000000)
    values: list[str] | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def require_domain(self) -> SampleParameter:
        if self.values is not None:
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("choose explicit values or an integer range")
            parsed = [bounded_number(v) for v in self.values]
            if len(set(parsed)) != len(parsed):
                raise ValueError("parameter values must be mathematically distinct")
        elif (
            self.minimum is None or self.maximum is None or self.minimum > self.maximum
        ):
            raise ValueError("parameter requires an ordered integer range")
        return self


class CorrectnessTemplate(Record):
    request: CorrectnessRequest
    parameters: list[SampleParameter] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def require_bound_parameters(self) -> CorrectnessTemplate:
        names = [p.name for p in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        references: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("param") is not None:
                    references.add(value["param"])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.request.model_dump(mode="json"))
        if references != set(names):
            raise ValueError("every parameter must be declared and used")
        return self


class SamplingSettings(Record):
    max_examples: int = Field(default=50, ge=1, le=200)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)


def instantiate(
    template: CorrectnessTemplate, parameters: dict[str, str]
) -> CorrectnessRequest:
    def bind(value: Any) -> Any:
        if isinstance(value, dict):
            if value.get("param") is not None:
                return {"num": parameters[value["param"]]}
            return {key: bind(child) for key, child in value.items()}
        if isinstance(value, list):
            return [bind(child) for child in value]
        return value

    return CorrectnessRequest.model_validate(
        bind(template.request.model_dump(mode="json"))
    )


def qualify_in_process(
    template: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
    definition = CorrectnessTemplate.model_validate(template)
    selected = SamplingSettings.model_validate(configuration)
    strategies = {
        p.name: st.sampled_from(p.values)
        if p.values is not None
        else st.integers(min_value=p.minimum, max_value=p.maximum).map(str)
        for p in definition.parameters
    }
    counts = dict.fromkeys(
        ("correct", "incorrect", "unknown", "unsupported", "timeout", "error"), 0
    )
    checked: dict[tuple[tuple[str, str], ...], str] = {}
    counterexample: dict[str, Any] | None = None
    first_unresolved: dict[str, Any] | None = None
    call_limit = selected.max_examples * 10 + 100
    calls = 0

    class IncorrectAnswer(AssertionError):
        pass

    class BudgetExhausted(Exception):
        pass

    @seed(selected.seed)
    @settings(
        max_examples=selected.max_examples,
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(st.fixed_dictionaries(strategies))
    def campaign(parameters: dict[str, str]) -> None:
        nonlocal calls, counterexample, first_unresolved
        calls += 1
        if calls > call_limit:
            raise BudgetExhausted
        key = tuple(sorted(parameters.items()))
        if key not in checked:
            result = check_in_process(instantiate(definition, parameters))
            checked[key] = result.outcome
            counts[result.outcome] += 1
            detail = {
                "parameters": parameters,
                "outcome": result.outcome,
                "reason": result.reason,
            }
            if result.outcome == "incorrect":
                counterexample = detail
            elif result.outcome != "correct" and first_unresolved is None:
                first_unresolved = detail
        if checked[key] == "incorrect":
            # Retain Hypothesis's final shrunk/replayed assignment.
            counterexample = {"parameters": parameters, "outcome": "incorrect"}
            raise IncorrectAnswer("candidate answer is mathematically incorrect")

    budget_exhausted = False
    try:
        campaign()
    except IncorrectAnswer:
        pass
    except BudgetExhausted:
        budget_exhausted = True
    status: Literal["passed", "failed", "inconclusive"] = "passed"
    if counts["incorrect"]:
        status = "failed"
    elif budget_exhausted or any(counts[name] for name in counts if name != "correct"):
        status = "inconclusive"
    return {
        "status": status,
        "checking_mode": "property_based",
        "cases_checked": len(checked),
        "counts": counts,
        "seed": selected.seed,
        "max_examples": selected.max_examples,
        "domain_size": _domain_size(definition),
        "counterexample": counterexample,
        "first_unresolved": first_unresolved,
        "budget_exhausted": budget_exhausted,
        "engine_version": "math-correctness/1",
        "hypothesis_version": hypothesis.__version__,
        "sympy_version": sympy.__version__,
        "scope": "Observed samples only; no universal correctness claim.",
    }


def _domain_size(template: CorrectnessTemplate) -> int:
    sizes: list[int] = []
    for parameter in template.parameters:
        if parameter.values is not None:
            sizes.append(len(parameter.values))
        else:
            assert parameter.minimum is not None and parameter.maximum is not None
            sizes.append(parameter.maximum - parameter.minimum + 1)
    return math.prod(sizes)
