"""Intermediate values shared by the ordered code-domain checks."""

import itertools
from dataclasses import dataclass, field
from typing import Any

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.code_types import ParameterValue
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.tools.python_execution import ExecutionResult


@dataclass
class DistractorCandidate:
    index: int
    expression: SafeExpression | None = None
    values: list[Any] | None = None
    rejection: str | None = None


@dataclass
class CodeValidationContext:
    template: CodeTemplateCandidate
    num_distractors: int | None = None
    names: tuple[str, ...] = field(init=False)
    inputs_cases: list[dict[str, ParameterValue]] = field(init=False)
    original_distractor_count: int = field(init=False)
    proposed_answer: SafeExpression | None = None
    candidates: list[DistractorCandidate] = field(default_factory=list)
    proposed_answers: list[Any] = field(default_factory=list)
    executions: list[ExecutionResult] = field(default_factory=list)
    canonical_answers: list[Any] = field(default_factory=list)
    corrected_cases: int = 0

    def __post_init__(self) -> None:
        # Checks may replace recipes; caller-owned candidates remain untouched.
        self.template = self.template.model_copy(deep=True)
        self.names = tuple(parameter.name for parameter in self.template.parameters)
        self.original_distractor_count = len(self.template.distractors)
        self.inputs_cases = [
            dict(zip(self.names, values, strict=True))
            for values in itertools.product(
                *(parameter.values for parameter in self.template.parameters)
            )
        ]

    @property
    def case_details(self) -> dict[str, int]:
        return {"cases": len(self.inputs_cases)}
