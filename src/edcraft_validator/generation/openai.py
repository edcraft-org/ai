import json
import os
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import GeneratedQuestion, ValidationReport

DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"

JsonScalar = str | int | float | bool | None


class OpenAIObjectEntry(BaseModel):
    key: str
    value: JsonScalar


class OpenAIJsonValue(BaseModel):
    """Schema-safe tagged representation of a JSON-compatible value."""

    kind: Literal["scalar", "list", "object"]
    scalar: JsonScalar
    items: list[JsonScalar]
    properties: list[OpenAIObjectEntry]

    def to_python(self) -> JsonScalar | list[JsonScalar] | dict[str, JsonScalar]:
        if self.kind == "list":
            return self.items
        if self.kind == "object":
            return {item.key: item.value for item in self.properties}
        return self.scalar


class OpenAIInput(BaseModel):
    name: str
    value: OpenAIJsonValue


class OpenAIQuestionDraftResponse(BaseModel):
    """Schema for the model-generated draft; it deliberately has no answer."""

    model_config = ConfigDict(extra="forbid")

    code: str
    entry_function: str
    inputs: list[OpenAIInput]
    question: str
    question_type: Literal["mcq"]


class OpenAIQuestionResponse(OpenAIQuestionDraftResponse):
    """Backward-compatible schema for callers using the old one-stage API."""

    proposed_answer: OpenAIJsonValue
    distractors: list[OpenAIJsonValue]


class OpenAIDistractorResponse(BaseModel):
    """Schema for distractors generated after Docker computes the answer."""

    model_config = ConfigDict(extra="forbid")

    distractors: list[OpenAIJsonValue]


class OpenAIGenerationError(RuntimeError):
    """Raised when OpenAI does not return a parsed question."""


class OpenAIQuestionGenerator:
    """Generate one candidate using OpenAI Structured Outputs."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
    ) -> None:
        self.client = client or OpenAI(
            api_key=_api_key(),
            base_url=_base_url(),
        )
        self.model = (
            model
            or os.getenv("GENERATION_MODEL")
            or (
                os.getenv("OLLAMA_MODEL")
                if os.getenv("GENERATION_PROVIDER", "soclaas").lower() == "ollama"
                else None
            )
            or os.getenv("SOCLAAS_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL
        )
        self.provider = os.getenv("GENERATION_PROVIDER", "soclaas").lower()

    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion:
        # Compatibility path for existing integrations. GenerationService uses
        # generate_draft()/generate_distractors() for the authoritative pipeline.
        parsed = self._request_model(
            _LEGACY_SYSTEM_PROMPT,
            _build_legacy_prompt(request, feedback),
            OpenAIQuestionResponse,
        )
        return GeneratedQuestion.model_validate(
            {
                "code": parsed.code,
                "entry_function": parsed.entry_function,
                "inputs": {item.name: item.value.to_python() for item in parsed.inputs},
                "question": parsed.question,
                "proposed_answer": parsed.proposed_answer.to_python(),
                "distractors": [item.to_python() for item in parsed.distractors],
                "question_type": parsed.question_type,
            }
        )

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft:
        parsed = self._request_model(
            _SYSTEM_PROMPT,
            _build_prompt(request, feedback),
            OpenAIQuestionDraftResponse,
        )
        return QuestionDraft(
            code=parsed.code,
            entry_function=parsed.entry_function,
            inputs={item.name: item.value.to_python() for item in parsed.inputs},
            question=parsed.question,
            question_type=parsed.question_type,
        )

    def generate_distractors(
        self,
        draft: QuestionDraft,
        answer: object,
        num_distractors: int,
        *,
        feedback: ValidationReport | None = None,
    ) -> list[object]:
        prompt = _build_distractor_prompt(draft, answer, num_distractors, feedback)
        parsed = self._request_model(
            _DISTRACTOR_SYSTEM_PROMPT,
            prompt,
            OpenAIDistractorResponse,
        )
        return [item.to_python() for item in parsed.distractors]

    def _request_model(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            if self.provider == "ollama":
                content = self._ollama_request(messages, schema)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
            if not content:
                raise ValueError("empty response")
            return schema.model_validate_json(content)
        except (IndexError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
            raise OpenAIGenerationError(
                f"Model returned invalid question JSON: {exc}"
            ) from exc

    def _ollama_request(
        self, messages: list[dict[str, str]], schema: type[BaseModel]
    ) -> str:
        """Call Ollama's native API so its decoder enforces the JSON schema."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0},
        }
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = json.load(response)
            return body["message"]["content"]
        except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _api_key() -> str | None:
    provider = os.getenv("GENERATION_PROVIDER", "soclaas").lower()
    if provider == "ollama":
        return os.getenv("OLLAMA_API_KEY") or "ollama"
    return os.getenv("SOCLAAS_API_KEY") or os.getenv("OPENAI_API_KEY")


def _base_url() -> str | None:
    provider = os.getenv("GENERATION_PROVIDER", "soclaas").lower()
    if provider == "ollama":
        return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return os.getenv("SOCLAAS_BASE_URL") or os.getenv("OPENAI_BASE_URL")


_SYSTEM_PROMPT = """\
Generate exactly one Python multiple-choice return-value question draft.

The generated code must stay within this validator's deliberately small subset:
- Define the entry function at module level and ask what that function returns.
- Use only expressions, assignments, if statements, and for loops.
- Direct calls may use only: abs, all, any, bool, enumerate, float, int, len,
  list, max, min, range, reversed, round, sorted, str, sum, tuple, and zip, or
  another module-level function defined in the generated code.
- Do not use imports, attributes, classes, decorators, recursion, comprehensions,
  while loops, lambdas, exceptions, file access, networking, input, eval, or exec.
- Encode every input with the tagged value schema: use kind=scalar with scalar set
  and empty items/properties; kind=list with items set, scalar=null, and empty
  properties; or kind=object with key/value properties, scalar=null, and empty
  items. Object property values must be scalar.
- Return code as one readable, correctly indented string with newline characters.
- Respond with a single valid JSON object and no markdown fences or extra text.
- The JSON object must have exactly these top-level keys: code, entry_function,
  inputs, question, question_type.
- Use this exact shape (values are illustrative):
  {"code":"def f(x):\\n    return x + 1","entry_function":"f",
   "inputs":[{"name":"x","value":{"kind":"scalar","scalar":2,
   "items":[],"properties":[]}}],"question":"What does f(2) return?",
   "proposed_answer":{"kind":"scalar","scalar":3,"items":[],
   "properties":[]},"distractors":[{"kind":"scalar","scalar":2,
   "items":[],"properties":[]}],"question_type":"mcq"}
- Every input must be an object with both name and value keys. The value object
  must always contain scalar, items, and properties; empty collections are []
  (never {}). question_type must be exactly "mcq".
The deterministic validator will execute the code and compute the answer. Do not
generate an answer or distractors in this response.
"""

_DISTRACTOR_SYSTEM_PROMPT = """\
Generate plausible but incorrect distractors for a Python return-value
multiple-choice question.
The correct answer was computed independently by the deterministic executor.
Return only one JSON object with exactly one key: distractors.
Use the tagged value schema for every distractor, with empty collections as [].
Every distractor must be unique, type-compatible with, and different from the
correct answer.
"""

# Kept for callers that still use the original one-request API.
_LEGACY_SYSTEM_PROMPT = _SYSTEM_PROMPT


def _build_prompt(
    request: GenerationRequest,
    feedback: ValidationReport | None,
) -> str:
    difficulty = {
        "beginner": "one concept and a short, direct calculation",
        "intermediate": "two or more steps, possibly including one branch or loop",
        "advanced": "several interacting steps while remaining easy to trace safely",
    }[request.difficulty]
    prompt = (
        f"Topic: {request.topic}\n"
        f"Difficulty: {request.difficulty} ({difficulty})\n"
        "Create the code, inputs, and question only. The answer and distractors "
        "will be generated in later stages."
    )
    if feedback is not None:
        issues = "; ".join(
            f"{issue.code}: {issue.message}" for issue in feedback.issues
        )
        prompt += (
            "\nThe previous candidate failed deterministic validation. "
            f"Correct these issues: {issues}"
        )
    return prompt


def _build_legacy_prompt(
    request: GenerationRequest,
    feedback: ValidationReport | None,
) -> str:
    prompt = _build_prompt(request, feedback)
    if feedback is not None and feedback.actual_answer is not None:
        prompt += f"\nThe executed return value was: {feedback.actual_answer!r}"
    return prompt + (
        "\nFor compatibility, include proposed_answer and distractors using the "
        "tagged value schema."
    )


def _build_distractor_prompt(
    draft: QuestionDraft,
    answer: object,
    num_distractors: int,
    feedback: ValidationReport | None,
) -> str:
    answer_shape = _value_shape(answer)
    prompt = (
        f"Code:\n{draft.code}\n"
        f"Entry function: {draft.entry_function}\n"
        f"Inputs: {draft.inputs!r}\n"
        f"Question: {draft.question}\n"
        f"Correct answer computed by Docker: {answer!r}\n"
        f"Correct answer shape: {answer_shape}. Every distractor must be one "
        f"{answer_shape} value, not a collection of answer options.\n"
        f"Generate exactly {num_distractors} distractors."
    )
    if answer_shape == "scalar number":
        prompt += (
            "\nFor example, the distractor values should look like "
            '{"kind":"scalar","scalar":14,"items":[],"properties":[]} '
            "rather than kind=list."
        )
    if feedback is not None:
        prompt += "\nPrevious distractors failed validation: " + "; ".join(
            f"{issue.code}: {issue.message}" for issue in feedback.issues
        )
    return prompt


def _value_shape(value: object) -> str:
    if isinstance(value, bool):
        return "scalar boolean"
    if isinstance(value, (int, float)):
        return "scalar number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "scalar string"
