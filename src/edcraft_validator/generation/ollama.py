import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from edcraft_validator.domains.code.capabilities import ParameterKind
from edcraft_validator.domains.code.templates import (
    CODE_TEMPLATE_PROMPT_VERSION,
    CODE_TEMPLATE_SYSTEM_PROMPT,
    CodeTemplateProposal,
    build_template_prompt,
    parse_code_template_proposal,
)
from edcraft_validator.generation.base import (
    GenerationError,
    GenerationResponseError,
    GenerationSchemaError,
    GenerationTimeoutError,
    GenerationTransportError,
    build_prompt_metadata,
)
from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplatePromptMetadata,
)

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
    values: list[str] = Field(
        min_length=2,
        max_length=4,
        description="Finite values encoded as strings according to the declared kind",
    )


class OllamaDistractorWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(min_length=1)
    reason_template: str = Field(min_length=1)


class OllamaProposalWire(BaseModel):
    """Provider-specific schema normalized into CodeTemplateProposal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(
        min_length=1,
        description=(
            "Learner-facing Python program that directly computes or traces the "
            "selected topic; never template-generation code"
        ),
    )
    entry_function: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Function in code that the learner reasons about",
    )
    parameters: list[OllamaParameterWire] = Field(min_length=1, max_length=3)
    answer_expression: str = Field(
        min_length=1,
        description="Expression over parameter names for the selected trace target",
    )
    distractors: list[OllamaDistractorWire] = Field(min_length=2, max_length=5)


class OllamaTemplateGenerator:
    """Author reusable templates through Ollama's native structured endpoint."""

    def __init__(
        self, client: object | None = None, *, model: str | None = None
    ) -> None:
        self.provider = "ollama"
        self.client = client
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"

    def generate_proposal(
        self, request: TemplateAuthoringRequest
    ) -> CodeTemplateProposal:
        try:
            content = self._ollama_request(
                self._messages(request),
                OllamaProposalWire,
            )
            if not content:
                raise GenerationResponseError("Ollama returned an empty response")
            return parse_ollama_proposal(content)
        except GenerationError:
            raise
        except json.JSONDecodeError as exc:
            raise GenerationResponseError(
                f"Ollama returned malformed JSON: {exc}"
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise GenerationSchemaError(
                f"Ollama proposal failed local schema validation: {exc}"
            ) from exc

    def prompt_metadata(
        self, request: TemplateAuthoringRequest
    ) -> TemplatePromptMetadata:
        return build_prompt_metadata(
            f"{CODE_TEMPLATE_PROMPT_VERSION}+ollama-wire-v1",
            self._messages(request),
        )

    @staticmethod
    def _messages(request: TemplateAuthoringRequest) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{build_template_prompt(request)}\n{OLLAMA_WIRE_GUIDANCE}",
            },
        ]

    def _ollama_request(
        self, messages: list[dict[str, str]], schema: type[BaseModel]
    ) -> str:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {
                "temperature": _temperature(),
                "num_predict": _num_predict(),
            },
        }
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout = _timeout_seconds()
            with urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            return body["message"]["content"]
        except TimeoutError as exc:
            raise GenerationTimeoutError(
                f"Ollama request timed out after {timeout:g} seconds"
            ) from exc
        except HTTPError as exc:
            raise GenerationTransportError(
                f"Ollama HTTP request failed with status {exc.code}"
            ) from exc
        except URLError as exc:
            raise GenerationTransportError(
                f"Ollama transport request failed: {exc.reason}"
            ) from exc
        except ConnectionError as exc:
            raise GenerationTransportError(
                f"Ollama connection was interrupted: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise GenerationResponseError(
                f"Ollama endpoint returned malformed response JSON: {exc}"
            ) from exc
        except (KeyError, TypeError) as exc:
            raise GenerationResponseError(
                "Ollama endpoint response did not contain message.content"
            ) from exc


def parse_ollama_proposal(content: str) -> CodeTemplateProposal:
    """Normalize the simple Ollama wire object into the shared proposal."""
    wire = OllamaProposalWire.model_validate(json.loads(content))
    payload = {
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
    return parse_code_template_proposal(json.dumps(payload))


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


def _timeout_seconds() -> float:
    raw_value = os.getenv("OLLAMA_TIMEOUT_SECONDS", "300").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise GenerationError("OLLAMA_TIMEOUT_SECONDS must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise GenerationError("OLLAMA_TIMEOUT_SECONDS must be greater than zero")
    return value


def _temperature() -> float:
    raw_value = os.getenv("OLLAMA_TEMPERATURE", "0").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise GenerationError("OLLAMA_TEMPERATURE must be a number") from exc
    if not math.isfinite(value) or not 0 <= value <= 2:
        raise GenerationError("OLLAMA_TEMPERATURE must be between 0 and 2")
    return value


def _num_predict() -> int:
    raw_value = os.getenv("OLLAMA_NUM_PREDICT", "2048").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise GenerationError("OLLAMA_NUM_PREDICT must be an integer") from exc
    if not 128 <= value <= 4096:
        raise GenerationError("OLLAMA_NUM_PREDICT must be between 128 and 4096")
    return value
