"""Domain-neutral limited property sampling, replay and shrinking.

A caller supplies finite parameter domains, a few explicit boundary examples,
and a predicate over one input mapping. The run samples inputs with Hypothesis
under an execution-call and wall-clock budget, records the first result for
each distinct input, and reports an exhausted budget as a validation failure.
No domain model is imported here.
"""

from __future__ import annotations

import copy
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from hypothesis import HealthCheck, Phase, example, given, seed, settings
from hypothesis import strategies as st

from edcraft_validator.validation.validation_contracts import ValidationFailure


@dataclass(frozen=True)
class PropertyCheckSettings:
    max_examples: int = 32
    max_execution_calls: int = 128
    timeout_seconds: float = 30.0
    seed: int = 0

    def __post_init__(self) -> None:
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
    whole_domain: bool = False

    @property
    def remaining_seconds(self) -> float:
        remaining = self.config.timeout_seconds - (time.perf_counter() - self.started)
        if remaining <= 0:
            raise _BudgetExceeded()
        return remaining

    def reserve_execution(self) -> None:
        _ = self.remaining_seconds
        if self.execution_calls >= self.config.max_execution_calls:
            raise _BudgetExceeded()
        self.execution_calls += 1

    def details(self) -> dict[str, Any]:
        return dict(
            checking_mode="property_based",
            examples_checked=len(self.passed),
            execution_calls=self.execution_calls,
            max_examples=self.config.max_examples,
            max_execution_calls=self.config.max_execution_calls,
            timeout_seconds=self.config.timeout_seconds,
            seed=self.config.seed,
            whole_domain=self.whole_domain,
        )

    def check(
        self,
        parameters: Mapping[str, Sequence[Any]],
        boundary: list[dict[str, Any]],
        property_check: Callable[[dict[str, Any], PropertyCheckRun], Any],
        *,
        cover_small_domain: bool = False,
    ) -> list[Any]:
        strategy = st.fixed_dictionaries(
            {name: st.sampled_from(values) for name, values in parameters.items()}
        )
        explicit_examples = self._explicit_examples(
            parameters, boundary, cover_small_domain=cover_small_domain
        )

        @seed(self.config.seed)
        @settings(
            max_examples=self.config.max_examples,
            deadline=None,
            database=None,
            report_multiple_bugs=False,
            phases=(Phase.explicit, Phase.generate, Phase.shrink),
            suppress_health_check=[
                HealthCheck.too_slow,
                HealthCheck.filter_too_much,
            ],
        )
        @given(inputs=strategy)
        def check_case(inputs):
            _ = self.remaining_seconds
            key = _dedup_key(inputs)
            # Replays of a passing input need no second execution. Failed inputs
            # are deliberately rechecked so shrinking remains a real property test.
            if key not in self.passed:
                value = property_check(copy.deepcopy(inputs), self)
                _ = self.remaining_seconds
                self.passed[key] = value

        for inputs in reversed(explicit_examples):
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

    def _explicit_examples(
        self,
        parameters: Mapping[str, Sequence[Any]],
        boundary: list[dict[str, Any]],
        *,
        cover_small_domain: bool,
    ) -> list[dict[str, Any]]:
        """Boundary examples first, then whole-domain coverage when it fits."""
        examples = list(boundary)
        if not cover_small_domain:
            return examples

        names = list(parameters)
        combination_count = math.prod(len(parameters[name]) for name in names)
        if combination_count > self.config.max_examples:
            return examples

        self.whole_domain = True
        seen = {_dedup_key(item) for item in examples}
        for values in product(*(parameters[name] for name in names)):
            inputs = dict(zip(names, values, strict=True))
            key = _dedup_key(inputs)
            if key not in seen:
                seen.add(key)
                examples.append(inputs)
        return examples


def _dedup_key(inputs: Mapping[str, Any]) -> str:
    """A stable key for JSON and non-JSON values such as ``Fraction``."""
    return json.dumps(inputs, sort_keys=True, default=str)
