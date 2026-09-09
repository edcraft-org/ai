"""Build structured generation requests for the code domain."""

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.domains.code.capabilities import ParameterKind
from edcraft_validator.domains.code.models import CodeTemplateRequest
from edcraft_validator.domains.code.templates import (
    CODE_TEMPLATE_PROMPT_VERSION,
    CODE_TEMPLATE_SYSTEM_PROMPT,
    CodeTemplateProposal,
    build_template_prompt,
    parse_code_template_proposal,
)
from edcraft_validator.generation.base import StructuredGenerationRequest

OLLAMA_WIRE_GUIDANCE = """\
Use the Ollama wire format for parameter values. Every item in `values` must be a
string: integers use decimal strings such as "2"; booleans use "true" or "false";
strings use their plain text; integer_list values use JSON-array strings such as
"[1,2]". Local validation converts these strings to the declared parameter kind.
"""


class OllamaParameterWire(BaseModel):
    """Simple non-recursive parameter representation for Ollama."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: ParameterKind
    values: list[str] = Field(min_length=2, max_length=4)


class OllamaDistractorWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(min_length=1)
    reason_template: str = Field(min_length=1)


class OllamaProposalWire(BaseModel):
    """Non-recursive code proposal used at the Ollama boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[OllamaParameterWire] = Field(min_length=1, max_length=3)
    answer_expression: str = Field(min_length=1)
    distractors: list[OllamaDistractorWire] = Field(min_length=2, max_length=5)


def build_code_generation_request(
    request: CodeTemplateRequest, *, provider: str
) -> StructuredGenerationRequest[CodeTemplateProposal]:
    """Return the prompt and response contract required by one provider."""
    system_message = {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT}
    user_prompt = build_template_prompt(request)

    if provider == "ollama":
        return StructuredGenerationRequest(
            messages=[
                system_message,
                {
                    "role": "user",
                    "content": f"{user_prompt}\n{OLLAMA_WIRE_GUIDANCE}",
                },
            ],
            response_model=OllamaProposalWire,
            parse_response=parse_ollama_proposal,
            prompt_version=f"{CODE_TEMPLATE_PROMPT_VERSION}+ollama-wire-v1",
        )

    return StructuredGenerationRequest(
        messages=[
            system_message,
            {"role": "user", "content": user_prompt},
        ],
        response_model=CodeTemplateProposal,
        parse_response=parse_code_template_proposal,
        prompt_version=CODE_TEMPLATE_PROMPT_VERSION,
    )


def parse_ollama_proposal(content: str) -> CodeTemplateProposal:
    """Convert the code domain's Ollama wire schema into its proposal model."""
    wire = OllamaProposalWire.model_validate(json.loads(content))
    return CodeTemplateProposal.model_validate(
        {
            "code": wire.code,
            "entry_function": wire.entry_function,
            "parameters": [
                {
                    "name": parameter.name,
                    "kind": parameter.kind,
                    "values": [
                        _parse_parameter_value(parameter.kind, value)
                        for value in parameter.values
                    ],
                }
                for parameter in wire.parameters
            ],
            "answer_expression": wire.answer_expression,
            "distractors": [
                distractor.model_dump(mode="json") for distractor in wire.distractors
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
