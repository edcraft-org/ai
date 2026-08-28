import os
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import ValidationReport

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
    """Schema for the model-generated draft and conceptual distractors."""

    model_config = ConfigDict(extra="forbid")

    code: str
    entry_function: str
    inputs: list[OpenAIInput]
    question: str
    distractors: list[OpenAIJsonValue]
    distractor_reasons: list[str]
    question_type: Literal["mcq"]


class OpenAIGenerationError(RuntimeError):
    """Raised when OpenAI does not return a parsed question."""


class OpenAICompatibleQuestionGenerator:
    """Generate a draft through an OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        provider: str,
        client: Any | None = None,
        *,
        model: str | None = None,
    ) -> None:
        if provider not in {"openai", "soclaas"}:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider = provider
        self.client = client or OpenAI(
            api_key=_api_key(provider),
            base_url=_base_url(provider),
        )
        self.model = (
            model
            or {
                "ollama": os.getenv("OLLAMA_MODEL"),
                "soclaas": os.getenv("SOCLAAS_MODEL"),
                "openai": os.getenv("OPENAI_MODEL"),
            }[provider]
            or DEFAULT_OPENAI_MODEL
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
            distractors=[item.to_python() for item in parsed.distractors],
            distractor_reasons=parsed.distractor_reasons,
            question_type=parsed.question_type,
        )

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


def _api_key(provider: str) -> str | None:
    return {
        "soclaas": os.getenv("SOCLAAS_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
    }[provider]


def _base_url(provider: str) -> str | None:
    return {
        "soclaas": os.getenv("SOCLAAS_BASE_URL"),
        "openai": os.getenv("OPENAI_BASE_URL"),
    }[provider]


_SYSTEM_PROMPT = """\
Generate exactly one Python multiple-choice return-value question with
conceptual distractors.

The generated code must stay within this validator's deliberately small subset:
- Define the entry function at module level and ask what that function returns.
- Use only expressions, assignments, if statements, and for loops.
- Direct calls may use only: abs, all, any, bool, enumerate, float, int, len,
  list, max, min, range, reversed, round, sorted, str, sum, tuple, and zip, or
  another module-level function defined in the generated code.
- Do not use imports, attributes, classes, decorators, recursion, comprehensions,
  while loops, lambdas, exceptions, file access, networking, input, eval, or exec.
- Encode every input, answer, and distractor with the tagged value schema: use
  kind=scalar with scalar set
  and empty items/properties; kind=list with items set, scalar=null, and empty
  properties; or kind=object with key/value properties, scalar=null, and empty
  items. Object property values must be scalar.
- Generate exactly the requested number of distractors together with the draft.
- Each distractor must represent a distinct conceptual misunderstanding, such as
  skipping a loop iteration, mishandling a branch, or applying an operation in
  the wrong order. Do not create arbitrary nearby numbers.
- Return code as one readable, correctly indented string with newline characters.
- Respond with a single valid JSON object and no markdown fences or extra text.
- The JSON object must have exactly these top-level keys: code, entry_function,
  inputs, question, distractors, distractor_reasons,
  question_type.
- Use this exact shape (values are illustrative):
  {"code":"def f(x):\\n    return x + 1","entry_function":"f",
   "inputs":[{"name":"x","value":{"kind":"scalar","scalar":2,
   "items":[],"properties":[]}}],"question":"What does f(2) return?",
   "distractors":[{"kind":"scalar","scalar":2,
   "items":[],"properties":[]}],"distractor_reasons":["adds one"],
   "question_type":"mcq"}
- Every input must be an object with both name and value keys. The value object
  must always contain scalar, items, and properties; empty collections are []
  (never {}). question_type must be exactly "mcq".
The deterministic validator will execute the code and use its return value as
the final answer. The generated distractors remain subject to validation.
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
        f"Create exactly {request.num_distractors} distractors. Create the code, "
        "inputs, question, distractors, and "
        "one misconception reason for each distractor."
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
