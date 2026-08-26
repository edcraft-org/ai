import os
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
    """Concrete schema used for OpenAI Structured Outputs."""

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
        self.client = client or OpenAI()
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)

    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_prompt(request, feedback)},
            ],
            text_format=OpenAIQuestionResponse,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise OpenAIGenerationError(
                "OpenAI returned no parsed question, possibly due to a refusal"
            )
        return GeneratedQuestion.model_validate(
            {
                "code": parsed.code,
                "entry_function": parsed.entry_function,
                "inputs": {
                    item.name: item.value.to_python() for item in parsed.inputs
                },
                "question": parsed.question,
                "proposed_answer": parsed.proposed_answer.to_python(),
                "distractors": [item.to_python() for item in parsed.distractors],
                "question_type": parsed.question_type,
            }
        )


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
