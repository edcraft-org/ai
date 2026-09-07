"""Data contracts for reusable code-question templates."""

from __future__ import annotations

import copy
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edcraft_validator.domains.code.capabilities import Difficulty, ProgrammingTopic
from edcraft_validator.generation.models import TemplateAuthoringProvenance
from edcraft_validator.models import AnswerTarget, GeneratedQuestion
from edcraft_validator.validation.contracts import ValidationEvidence

MAX_TEMPLATE_CASES = 64
MAX_STRING_LENGTH = 40
MAX_LIST_LENGTH = 8
ParameterValue = int | bool | str | list[int]


class FiniteParameter(BaseModel):
    """A finite parameter domain that can be validated exhaustively."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: Literal["integer", "boolean", "string", "integer_list"]
    values: list[ParameterValue] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_values(self) -> FiniteParameter:
        encoded = [
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in self.values
        ]
        if len(encoded) != len(set(encoded)):
            raise ValueError("parameter values must be unique")
        validators = {
            "integer": self._validate_integer,
            "boolean": self._validate_boolean,
            "string": self._validate_string,
            "integer_list": self._validate_integer_list,
        }
        for value in self.values:
            validators[self.kind](value)
        return self

    @staticmethod
    def _validate_integer(value: ParameterValue) -> None:
        if type(value) is not int or abs(value) > 100:
            raise ValueError("integer values must be integers from -100 to 100")

    @staticmethod
    def _validate_boolean(value: ParameterValue) -> None:
        if type(value) is not bool:
            raise ValueError("boolean values must be true or false")

    @staticmethod
    def _validate_string(value: ParameterValue) -> None:
        if (
            type(value) is not str
            or not value
            or len(value) > MAX_STRING_LENGTH
            or not value.isprintable()
        ):
            raise ValueError(
                f"string values must be 1 to {MAX_STRING_LENGTH} printable characters"
            )

    @staticmethod
    def _validate_integer_list(value: ParameterValue) -> None:
        if type(value) is not list or len(value) > MAX_LIST_LENGTH:
            raise ValueError(
                f"integer-list values must contain at most {MAX_LIST_LENGTH} items"
            )
        if any(type(item) is not int or abs(item) > 100 for item in value):
            raise ValueError("integer-list items must be integers from -100 to 100")


class DistractorRecipe(BaseModel):
    """A deterministic misconception applied to concrete parameter values."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(min_length=1)
    reason_template: str = Field(min_length=1)


class CodeTemplateProposal(BaseModel):
    """Model-authored fields that require generative judgment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[FiniteParameter] = Field(min_length=1, max_length=3)
    answer_expression: str = Field(min_length=1)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=5)

    @field_validator("code", "answer_expression")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_domain(self) -> CodeTemplateProposal:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        combinations = math.prod(len(parameter.values) for parameter in self.parameters)
        if combinations > MAX_TEMPLATE_CASES:
            raise ValueError(
                f"template has {combinations} cases; maximum is {MAX_TEMPLATE_CASES}"
            )
        return self


class CodeQuestionTemplate(BaseModel):
    """Provider-neutral template contract for the first code-domain version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    topic: ProgrammingTopic
    difficulty: Difficulty
    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[FiniteParameter] = Field(min_length=1, max_length=3)
    question_template: str = Field(min_length=1)
    answer_target: AnswerTarget
    answer_expression: str | None = Field(default=None, min_length=1)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=8)
    question_type: Literal["mcq"]

    @field_validator("code", "question_template")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("answer_expression")
    @classmethod
    def reject_blank_answer_expression(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_domain(self) -> CodeQuestionTemplate:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        combinations = _case_count(self)
        if combinations > MAX_TEMPLATE_CASES:
            raise ValueError(
                f"template has {combinations} cases; maximum is {MAX_TEMPLATE_CASES}"
            )
        return self


class ValidatedTemplateCase(BaseModel):
    """One executor-derived answer from the template's finite input domain."""

    model_config = ConfigDict(extra="forbid", strict=True)

    inputs: dict[str, ParameterValue]
    answer: Any

    @field_validator("answer")
    @classmethod
    def require_finite_json_answer(cls, value: Any) -> Any:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("answer must be a finite JSON value") from exc
        return value


class TemplateValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    validator_version: str = Field(min_length=1)
    cases_validated: int = Field(ge=1)
    validated_cases: list[ValidatedTemplateCase] = Field(min_length=1)
    evidence: list[ValidationEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def require_successful_unique_evidence(self) -> TemplateValidationSummary:
        checks = [item.check for item in self.evidence]
        if len(checks) != len(set(checks)):
            raise ValueError("validation evidence checks must be unique")
        if any(item.status != "passed" for item in self.evidence):
            raise ValueError("approved templates require passing validation evidence")
        if self.cases_validated != len(self.validated_cases):
            raise ValueError("cases_validated must match validated_cases")
        return self


class ApprovedCodeQuestionTemplate(BaseModel):
    """A template plus evidence that its complete finite domain was checked."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template: CodeQuestionTemplate
    validation: TemplateValidationSummary
    authoring: TemplateAuthoringProvenance | None = None

    @model_validator(mode="after")
    def require_canonical_answers(self) -> ApprovedCodeQuestionTemplate:
        if self.template.answer_expression is not None:
            raise ValueError("approved templates must use validator-derived answers")
        return self


class TemplateQuestionInstance(BaseModel):
    """A reproducible question expanded from an approved template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str
    seed: int
    parameters: dict[str, ParameterValue]
    question: GeneratedQuestion


class TemplateValidationError(ValueError):
    """Raised when any possible instance fails template approval."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TEMPLATE_INVALID",
        field: str | None = None,
        inputs: dict[str, ParameterValue] | None = None,
        evidence: list[ValidationEvidence] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.inputs = copy.deepcopy(inputs)
        self.evidence = copy.deepcopy(evidence or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "field": self.field,
            "inputs": self.inputs,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
        }


def _case_count(template: CodeQuestionTemplate) -> int:
    combinations = 1
    for parameter in template.parameters:
        combinations *= len(parameter.values)
    return combinations
