import os
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from edcraft_validator.generation.models import GenerationRequest
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


class OpenAIQuestionResponse(BaseModel):
    """Schema used to validate the model's JSON response locally."""

    model_config = ConfigDict(extra="forbid")

    code: str
    entry_function: str
    inputs: list[OpenAIInput]
    question: str
    proposed_answer: OpenAIJsonValue
    distractors: list[OpenAIJsonValue]
    question_type: Literal["mcq"]


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
        try:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_prompt(request, feedback)},
            ]
            if self.provider == "ollama":
                content = self._ollama_request(messages)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
            if not content:
                raise ValueError("empty response")
            parsed = OpenAIQuestionResponse.model_validate_json(content)
        except (IndexError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
            raise OpenAIGenerationError(
                f"Model returned invalid question JSON: {exc}"
            ) from exc
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

    def _ollama_request(self, messages: list[dict[str, str]]) -> str:
        """Call Ollama's native API so its decoder enforces the JSON schema."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": OpenAIQuestionResponse.model_json_schema(),
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
Generate exactly one Python multiple-choice return-value question.

The generated code must stay within this validator's deliberately small subset:
- Define the entry function at module level and ask what that function returns.
- Use only expressions, assignments, if statements, and for loops.
- Direct calls may use only: abs, all, any, bool, enumerate, float, int, len,
  list, max, min, range, reversed, round, sorted, str, sum, tuple, and zip, or
  another module-level function defined in the generated code.
- Do not use imports, attributes, classes, decorators, recursion, comprehensions,
  while loops, lambdas, exceptions, file access, networking, input, eval, or exec.
- Encode every input, answer, and distractor with the tagged value schema:
  use kind=scalar with scalar set and empty items/properties; kind=list with items
  set, scalar=null, and empty properties; or kind=object with key/value properties,
  scalar=null, and empty items. Object property values must be scalar.
- Make every distractor unique, plausible, and different from the correct answer.
- Return code as one readable, correctly indented string with newline characters.
- Respond with a single valid JSON object and no markdown fences or extra text.
- The JSON object must have exactly these top-level keys: code, entry_function,
  inputs, question, proposed_answer, distractors, question_type.
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
The deterministic validator will execute the code and independently check the answer.
"""


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
        f"Create exactly {request.num_distractors} distractors."
    )
    if feedback is not None:
        issues = "; ".join(
            f"{issue.code}: {issue.message}" for issue in feedback.issues
        )
        prompt += (
            "\nThe previous candidate failed deterministic validation. "
            f"Correct these issues: {issues}"
        )
        if feedback.actual_answer is not None:
            prompt += f"\nThe executed return value was: {feedback.actual_answer!r}"
    return prompt
