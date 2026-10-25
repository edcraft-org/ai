"""Bounded Hypothesis sampling, replay and shrinking of template properties."""

import copy
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hypothesis import HealthCheck, Phase, example, given, seed, settings
from hypothesis import strategies as st

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.validation.validation_contracts import ValidationFailure


@dataclass(frozen=True)
class PropertyCheckSettings:
    max_examples: int = 32
    max_execution_calls: int = 128
    timeout_seconds: float = 30.0
    seed: int = 0

    def __post_init__(self):
        if (
            any(
                type(n) is not int or n <= 0
                for n in (self.max_examples, self.max_execution_calls)
            )
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("property checking budgets must be finite and positive")


class _BudgetExceeded(BaseException):
    """Stop the property engine immediately, including its shrinking phase."""


@dataclass
class PropertyCheckRun:
    config: PropertyCheckSettings
    execution_calls: int = 0
    started: float = field(default_factory=time.perf_counter)
    passed: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_seconds(self):
        remaining = self.config.timeout_seconds - (time.perf_counter() - self.started)
        if remaining <= 0:
            raise _BudgetExceeded()
        return remaining

    def reserve_execution(self):
        _ = self.remaining_seconds
        if self.execution_calls >= self.config.max_execution_calls:
            raise _BudgetExceeded()
        self.execution_calls += 1

    def details(self):
        return dict(
            checking_mode="property_based",
            examples_checked=len(self.passed),
            execution_calls=self.execution_calls,
            max_examples=self.config.max_examples,
            max_execution_calls=self.config.max_execution_calls,
            timeout_seconds=self.config.timeout_seconds,
            seed=self.config.seed,
        )

    def check(
        self,
        candidate: CodeTemplateCandidate,
        property_check: Callable[[dict, "PropertyCheckRun"], Any],
    ):
        strategy = st.fixed_dictionaries(
            {p.name: st.sampled_from(p.values) for p in candidate.parameters}
        )

        @seed(self.config.seed)
        @settings(
            max_examples=self.config.max_examples,
            deadline=None,
            database=None,
            report_multiple_bugs=False,
            phases=(Phase.explicit, Phase.generate, Phase.shrink),
            suppress_health_check=[HealthCheck.too_slow],
        )
        @given(inputs=strategy)
        def check_case(inputs):
            _ = self.remaining_seconds
            key = json.dumps(inputs, sort_keys=True)
            # Replays of a passing input need no second execution. Failed inputs
            # are deliberately rechecked so shrinking remains a real property test.
            if key not in self.passed:
                value = property_check(copy.deepcopy(inputs), self)
                _ = self.remaining_seconds
                self.passed[key] = value

        for inputs in reversed(boundary_examples(candidate)):
            check_case = example(inputs=inputs)(check_case)
        try:
            check_case()
        except _BudgetExceeded:
            raise ValidationFailure(
                "Property checking exhausted its execution or time budget",
                code="PROPERTY_CHECK_BUDGET_EXCEEDED",
                context=self.details(),
            ) from None
        except ValidationFailure as exc:
            exc.context.update(self.details())
            raise
        return list(self.passed.values())


def boundary_examples(candidate: CodeTemplateCandidate) -> list[dict]:
    """A few axis boundaries, not a Cartesian product or a coverage claim."""
    ordered = {}
    for p in candidate.parameters:
        values = p.values
        if p.kind in {"integer", "boolean"}:
            values = sorted(values)
        elif p.kind == "integer_list":
            values = sorted(values, key=lambda x: (len(x), x))
        ordered[p.name] = values
    base = {name: values[0] for name, values in ordered.items()}
    examples = [base, {name: values[-1] for name, values in ordered.items()}]
    for p in candidate.parameters:
        examples.append(base | {p.name: ordered[p.name][-1]})
        if p.kind == "integer" and 0 in p.values:
            examples.append(base | {p.name: 0})
    unique = {json.dumps(x, sort_keys=True): x for x in examples}
    return list(unique.values())
