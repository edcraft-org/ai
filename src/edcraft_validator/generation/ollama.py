import json
import os
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, create_model

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.generation.openai import (
    OpenAICompatibleQuestionGenerator,
    OpenAIGenerationError,
)
from edcraft_validator.generation.provider import (
    JsonScalar,
    QuestionDraftResponse,
    build_prompt,
    normalize_plain_response,
)
from edcraft_validator.models import ValidationReport

PlainJsonValue = JsonScalar | list[JsonScalar] | dict[str, JsonScalar]


class OllamaQuestionGenerator(OpenAICompatibleQuestionGenerator):
    """Generate drafts through Ollama while honoring the shared provider contract."""

    def __init__(
        self, client: object | None = None, *, model: str | None = None
    ) -> None:
        self.provider = "ollama"
        self.client = client
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"

    def generate_draft(
        self, request: GenerationRequest, *, feedback: ValidationReport | None = None
    ) -> QuestionDraft:
        wire_schema = _ollama_wire_schema(request.num_distractors)
        user_prompt = build_prompt(request, feedback)
        if feedback is not None and feedback.actual_answer is not None:
            user_prompt += (
                f"\nThe deterministic executor computed the normal return value as "
                f"{feedback.actual_answer!r}. Do not include that exact value in "
                "any distractor. Recalculate every distractor before responding."
            )
        parsed = self._request_model(
            _OLLAMA_SYSTEM_PROMPT,
            user_prompt,
            wire_schema,
        )
        try:
            return parsed.to_draft()
        except Exception as exc:
            raise OpenAIGenerationError(
                f"ollama returned a draft that failed local validation: {exc}"
            ) from exc

    def _request_model(
        self, system_prompt: str, user_prompt: str, schema: type[BaseModel]
    ) -> QuestionDraftResponse:
        try:
            content = self._ollama_request(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                schema,
            )
            if not content:
                raise ValueError("empty response")
            wire_response = schema.model_validate(json.loads(content))
            wire_data = wire_response.model_dump()
            distractor_pairs = wire_data["distractors"]
            wire_data["distractors"] = [pair["value"] for pair in distractor_pairs]
            wire_data["distractor_reasons"] = [
                pair["reason"] for pair in distractor_pairs
            ]
            return QuestionDraftResponse.model_validate(
                normalize_plain_response(wire_data)
            )
        except Exception as exc:
            raise OpenAIGenerationError(
                f"ollama returned invalid question JSON: {exc}"
            ) from exc

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
            "options": {"temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))},
        }
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
            with urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            return body["message"]["content"]
        except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc


class OllamaWireDistractor(BaseModel):
    """Pair a distractor value with the misconception that creates it."""

    model_config = ConfigDict(extra="forbid")
    value: PlainJsonValue
    reason: str = Field(min_length=1)


class OllamaWireResponse(BaseModel):
    """Flat Ollama wire contract; semantic validation happens locally."""

    model_config = ConfigDict(extra="forbid")
    code: str
    entry_function: str
    inputs: dict[str, PlainJsonValue]
    question: str
    distractors: list[OllamaWireDistractor]
    question_type: Literal["mcq"]


def _ollama_wire_schema(num_distractors: int) -> type[OllamaWireResponse]:
    """Build a concrete native schema with request-specific list lengths."""
    return create_model(
        "OllamaWireResponse",
        __base__=OllamaWireResponse,
        distractors=(
            list[OllamaWireDistractor],
            Field(min_length=num_distractors, max_length=num_distractors),
        ),
    )


_OLLAMA_SYSTEM_PROMPT = """\
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
- Use plain JSON values. Inputs must be an object mapping function argument names
  to values. Distractors must be an array of objects, each with exactly two keys:
  value (a raw JSON value) and reason (a string). Do not use tagged
  kind/scalar/items/properties structures. Lists and objects may contain only
  scalar values.
- Generate exactly the requested number of distractors. Every distractor must be
  unique, different from the correct answer, and represent a distinct conceptual
  misunderstanding such as skipping a loop iteration, mishandling a branch, or
  applying an operation in the wrong order. Do not create arbitrary nearby numbers.
- First calculate the correct return value. Then choose a misconception, calculate
  the exact value caused by that misconception, and put that value together with
  its matching explanation in one distractor object. Verify that every distractor
  value is different from the correct answer and that its reason describes how
  that exact value was obtained. For numeric distractors, include the mistaken
  operation and its resulting value in the reason; never use vague explanations
  such as "calculation error". Never choose a value independently of its reason.
- Before responding, perform this checklist: (1) execute the function mentally
  with the supplied inputs, (2) write down the correct return value, (3) compare
  every distractor value against it and replace any equal value, (4) verify that
  each reason describes the exact value beside it, and (5) verify that no reason
  claims the distractor is the correct calculation.
- Return code as one readable, correctly indented string with newline characters.
- Respond with a single valid JSON object and no markdown fences or extra text.
- The JSON object must have exactly these top-level keys: code, entry_function,
  inputs, question, distractors, distractor_reasons, question_type.
- Use this exact shape (values are illustrative):
  {"code":"def f(x):\\n    return x + 1","entry_function":"f",
   "inputs":{"x":2},"question":"What does f(2) return?",
   "distractors":[
     {"value":2,"reason":"does not add one"},
     {"value":4,"reason":"adds two instead of one"},
     {"value":0,"reason":"subtracts one instead of adding one"}],
   "question_type":"mcq"}
- Do not include a proposed_answer or any other key. The deterministic validator
  will execute the code and independently compute the final answer.
"""
