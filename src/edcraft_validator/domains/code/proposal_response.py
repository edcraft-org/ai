"""Typed LLM response schema for code proposals."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateContent,
    DistractorRecipe,
    FiniteParameter,
)


class IntegerParameterResponse(FiniteParameter):
    """Integer parameter represented with native JSON numbers."""

    kind: Literal["integer"]
    values: list[int] = Field(min_length=2, max_length=4)


class BooleanParameterResponse(FiniteParameter):
    """Boolean parameter represented with native JSON booleans."""

    kind: Literal["boolean"]
    values: list[bool] = Field(min_length=2, max_length=4)


class StringParameterResponse(FiniteParameter):
    """String parameter represented with native JSON strings."""

    kind: Literal["string"]
    values: list[str] = Field(min_length=2, max_length=4)


class IntegerListParameterResponse(FiniteParameter):
    """Integer-list parameter represented with native nested JSON arrays."""

    kind: Literal["integer_list"]
    values: list[list[int]] = Field(min_length=2, max_length=4)


CodeParameterResponse = (
    IntegerParameterResponse
    | BooleanParameterResponse
    | StringParameterResponse
    | IntegerListParameterResponse
)


class CodeProposalResponse(CodeTemplateContent):
    """Provider-independent typed response schema for a code proposal."""

    parameters: list[CodeParameterResponse] = Field(min_length=1, max_length=3)

    @field_validator(
        "code",
        mode="before",
        json_schema_input_type=Annotated[
            list[str], Field(min_length=1, max_length=160)
        ],
    )
    @classmethod
    def join_indented_lines(cls, value):
        # Canonical Python callers may still supply a string. The model's wire
        # schema requires lines, preserving indentation without escaped newlines.
        if isinstance(value, list) and all(isinstance(line, str) for line in value):
            if not 1 <= len(value) <= 160 or any(
                "\n" in line or "\r" in line for line in value
            ):
                raise ValueError("code must contain 1 to 160 individual Python lines")
            return "\n".join(value)
        return value

    @field_serializer("code", when_used="json")
    def serialize_code_lines(self, value: str) -> list[str]:
        return value.split("\n")


class CodeDistractorRevision(BaseModel):
    """Only recipes and parameter values may change after a distractor failure."""

    model_config = ConfigDict(extra="forbid", strict=True)

    parameters: list[CodeParameterResponse] = Field(min_length=1, max_length=3)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=5)
