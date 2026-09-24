"""Typed LLM response schema for code proposals."""

from typing import Literal

from pydantic import Field

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateProposal,
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


class CodeProposalResponse(CodeTemplateProposal):
    """Provider-independent typed response schema for a code proposal."""

    parameters: list[CodeParameterResponse] = Field(min_length=1, max_length=3)
