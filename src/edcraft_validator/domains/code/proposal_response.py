"""LLM response schema and conversion into canonical code proposals."""

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateProposal,
)
from edcraft_validator.domains.code.code_types import ParameterKind


class CodeParameterResponse(BaseModel):
    """Provider-independent parameter representation for code proposals."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: ParameterKind
    values: list[str] = Field(min_length=2, max_length=4)


class CodeDistractorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(min_length=1)
    reason_template: str = Field(min_length=1)


class CodeProposalResponse(BaseModel):
    """Provider-independent response schema for a code proposal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[CodeParameterResponse] = Field(min_length=1, max_length=3)
    answer_expression: str = Field(min_length=1)
    distractors: list[CodeDistractorResponse] = Field(min_length=2, max_length=5)


def parse_code_proposal_response(content: str) -> CodeTemplateProposal:
    """Convert the common response schema into the canonical proposal model."""
    response = CodeProposalResponse.model_validate(json.loads(content))
    return CodeTemplateProposal.model_validate(
        {
            "code": response.code,
            "entry_function": response.entry_function,
            "parameters": [
                {
                    "name": parameter.name,
                    "kind": parameter.kind,
                    "values": [
                        _parse_parameter_value(parameter.kind, value)
                        for value in parameter.values
                    ],
                }
                for parameter in response.parameters
            ],
            "answer_expression": response.answer_expression,
            "distractors": [
                distractor.model_dump(mode="json")
                for distractor in response.distractors
            ],
        }
    )


def _parse_parameter_value(kind: ParameterKind, value: str) -> object:
    if kind == "integer":
        if not re.fullmatch(r"[+-]?\d+", value):
            raise ValueError(f"invalid integer wire value {value!r}")
        return int(value)
    if kind == "boolean":
        try:
            return {"true": True, "false": False}[value.lower()]
        except KeyError as exc:
            raise ValueError(f"invalid boolean wire value {value!r}") from exc
    if kind == "string":
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid integer_list wire value {value!r}") from exc
    if not isinstance(parsed, list) or any(type(item) is not int for item in parsed):
        raise ValueError(f"invalid integer_list wire value {value!r}")
    return parsed
