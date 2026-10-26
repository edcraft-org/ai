"""Canonical request, proposal, template, and question schemas for code."""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.code.code_types import (
    AnswerTarget,
    Difficulty,
    ParameterValue,
    ProgrammingTopic,
)
from edcraft_validator.validation.validation_contracts import (
    ValidationEvidence,
    ValidationFailure,
)


class GeneratedQuestion(BaseModel):
    """A deterministic question expanded from a validated template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, Any]
    question: str = Field(min_length=1)
    proposed_answer: Any
    distractors: list[Any] = Field(min_length=2)
    distractor_reasons: list[str] = Field(default_factory=list)
    answer_target: AnswerTarget = "return_value"
    question_type: Literal["mcq"] = "mcq"

    @field_validator("code", mode="before", json_schema_input_type=str | list[str])
    @classmethod
    def join_code_lines(cls, value: Any) -> Any:
        """Normalize readable JSON line arrays to executable Python source."""
        if isinstance(value, list) and all(isinstance(line, str) for line in value):
            return "\n".join(value)
        return value

    @field_validator("code", "question")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class CodeTemplateRequest(BaseModel):
    """Free-form authoring request for one reusable code template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(min_length=1, max_length=4000)
    difficulty: Difficulty
    num_distractors: int = Field(default=3, ge=2, le=3)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


MAX_STRING_LENGTH = 40


MAX_LIST_LENGTH = 8


class FiniteParameter(BaseModel):
    """A bounded set of allowed values sampled during property-based checking."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: Literal["integer", "boolean", "string", "integer_list"]
    values: list[ParameterValue] = Field(min_length=2, max_length=32)

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

    expression: str = Field(
        min_length=1,
        description="Python expression using bare parameter names, for example a - b.",
    )
    reason_template: str = Field(min_length=1)


class CodeTemplateContent(BaseModel):
    """Model-authored fields that require generative judgment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    question_template: str = Field(min_length=1)
    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[FiniteParameter] = Field(min_length=1, max_length=3)
    answer_target: AnswerTarget
    answer_expression: str = Field(min_length=1)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=5)

    @field_validator("question_template", "code", "answer_expression")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_domain(self) -> CodeTemplateContent:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        return self


class CodeTemplateProposal(CodeTemplateContent):
    """Canonical model-authored proposal, including its sampled answer recipe."""


class CodeTemplateCandidate(BaseModel):
    """Provider-neutral template contract for the first code-domain version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    topic: ProgrammingTopic | None = None
    difficulty: Difficulty
    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[FiniteParameter] = Field(min_length=1, max_length=3)
    question_template: str = Field(min_length=1)
    answer_target: AnswerTarget
    answer_expression: str = Field(min_length=1)
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
    def reject_blank_answer_expression(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_domain(self) -> CodeTemplateCandidate:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        return self


class TemplateValidationSummary(BaseModel):
    """Sampled evidence, without a complete-domain answer table."""

    model_config = ConfigDict(extra="forbid", strict=True)

    validator_version: Literal["mcp-code-template-v2"] = "mcp-code-template-v2"
    checking_mode: Literal["property_based"]
    examples_checked: int = Field(ge=1)
    execution_calls: int = Field(ge=1)
    max_examples: int = Field(ge=1)
    max_execution_calls: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    seed: int
    evidence: list[ValidationEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def require_successful_unique_evidence(self) -> TemplateValidationSummary:
        checks = [item.check for item in self.evidence]
        if len(checks) != len(set(checks)):
            raise ValueError("validation evidence checks must be unique")
        if any(item.status != "passed" for item in self.evidence):
            raise ValueError("checked templates require passing validation evidence")
        if (
            not self.examples_checked
            <= self.execution_calls
            <= self.max_execution_calls
        ):
            raise ValueError("sample and execution counts exceed the checking budget")
        return self


class ValidatedCodeTemplate(ValidatedTemplateArtifact):
    """A template whose recipes passed sampled checks; manual review is required."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format_version: Literal["2.0.0"] = "2.0.0"
    template: CodeTemplateCandidate
    validation: TemplateValidationSummary


class CodeQuestionInstance(BaseModel):
    """A reproducible question expanded from a validated template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str
    artifact_id: str | None = None
    seed: int
    parameters: dict[str, ParameterValue]
    question: GeneratedQuestion
    requires_manual_review: Literal[True] = True


class TemplateValidationError(ValidationFailure):
    """Raised when a static check or sampled property fails."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TEMPLATE_INVALID",
        field: str | None = None,
        inputs: dict[str, ParameterValue] | None = None,
        evidence: list[ValidationEvidence] | None = None,
    ) -> None:
        context = {"failing_inputs": inputs} if inputs is not None else None
        super().__init__(
            message,
            code=code,
            field=field,
            context=context,
            evidence=evidence,
        )
        self.inputs = copy.deepcopy(inputs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "field": self.field,
            "inputs": self.inputs,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
        }


def parse_code_template_candidate(content: str) -> CodeTemplateCandidate:
    """Parse template JSON with strict local schema validation."""
    payload = json.loads(content)
    return CodeTemplateCandidate.model_validate(payload)


def parse_code_template_proposal(content: str) -> CodeTemplateProposal:
    """Parse an already canonical proposal with strict local schema validation."""
    payload = json.loads(content)
    return CodeTemplateProposal.model_validate(payload)
