"""Shared contract and utilities for OpenAI-compatible generators."""

from __future__ import annotations

import ast
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import ValidationReport

JsonScalar = str | int | float | bool | None


class TaggedJsonObjectEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: TaggedJsonValue


class TaggedJsonValue(BaseModel):
    """A recursively tagged JSON value suitable for model output."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["scalar", "list", "object"]
    scalar: JsonScalar
    items: list[TaggedJsonValue]
    properties: list[TaggedJsonObjectEntry]

    @model_validator(mode="after")
    def validate_shape(self) -> TaggedJsonValue:
        if self.kind == "scalar" and (self.items or self.properties):
            raise ValueError("scalar values must have empty items and properties")
        if self.kind == "list" and (self.scalar is not None or self.properties):
            raise ValueError("list values must have null scalar and empty properties")
        if self.kind == "object" and (self.scalar is not None or self.items):
            raise ValueError("object values must have null scalar and empty items")
        return self

    def to_python(self) -> Any:
        if self.kind == "list":
            return [item.to_python() for item in self.items]
        if self.kind == "object":
            return {item.key: item.value.to_python() for item in self.properties}
        return self.scalar


class TaggedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: TaggedJsonValue


class QuestionDraftResponse(BaseModel):
    """Provider-neutral model response contract."""

    model_config = ConfigDict(extra="forbid")
    code: str
    entry_function: str
    inputs: list[TaggedInput]
    question: str
    distractors: list[TaggedJsonValue] = Field(min_length=2)
    distractor_reasons: list[str] = Field(min_length=2)
    question_type: Literal["mcq"]

    @model_validator(mode="after")
    def validate_distractor_reasons(self) -> QuestionDraftResponse:
        if len(self.distractors) != len(self.distractor_reasons):
            raise ValueError("one distractor reason is required for each distractor")
        return self

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_shapes(cls, value: Any) -> Any:
        """Canonicalize equivalent tagged JSON shapes before strict validation."""
        if not isinstance(value, dict):
            return value
        normalized = _normalize_tagged_collections(value)
        inputs = normalized.get("inputs")
        if isinstance(inputs, dict) and inputs.get("kind") == "list":
            inputs = inputs.get("items", [])
        elif isinstance(inputs, dict) and inputs.get("kind") == "object":
            inputs = [
                {"name": entry["key"], "value": entry["value"]}
                for entry in inputs.get("properties", [])
                if isinstance(entry, dict) and "key" in entry and "value" in entry
            ]
        if isinstance(inputs, list):
            names = _function_argument_names(normalized.get("code"))
            records = []
            for index, item in enumerate(inputs):
                if isinstance(item, TaggedInput):
                    records.append(item)
                    continue
                if isinstance(item, dict) and {"name", "value"} <= item.keys():
                    records.append(item)
                    continue
                if isinstance(item, dict) and item.get("kind") == "object":
                    properties = {
                        entry.get("key"): entry.get("value")
                        for entry in item.get("properties", [])
                        if isinstance(entry, dict)
                    }
                    if "name" in properties and "value" in properties:
                        name = properties["name"]
                        if isinstance(name, dict) and name.get("kind") == "scalar":
                            name = name.get("scalar")
                        records.append({"name": name, "value": properties["value"]})
                        continue
                if index < len(names):
                    records.append({"name": names[index], "value": item})
                else:
                    records.append(item)
            normalized["inputs"] = records
        return normalized

    def to_draft(self) -> QuestionDraft:
        return QuestionDraft(
            code=self.code,
            entry_function=self.entry_function,
            inputs={item.name: item.value.to_python() for item in self.inputs},
            question=self.question,
            distractors=[item.to_python() for item in self.distractors],
            distractor_reasons=self.distractor_reasons,
            question_type=self.question_type,
        )


def _normalize_tagged_collections(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_tagged_collections(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {
        key: _normalize_tagged_collections(item) for key, item in value.items()
    }
    if normalized.get("kind") == "object" and isinstance(
        normalized.get("properties"), dict
    ):
        normalized["properties"] = [
            {"key": key, "value": item}
            for key, item in normalized["properties"].items()
        ]
    elif isinstance(normalized.get("properties"), dict):
        normalized["properties"] = []
    return normalized


def _function_argument_names(code: Any) -> list[str]:
    if not isinstance(code, str):
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [argument.arg for argument in node.args.args]
    return []


def normalize_plain_response(value: Any) -> Any:
    """Convert Ollama-style plain JSON into the shared tagged response shape."""
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    code = normalized.get("code")
    if "entry_function" not in normalized:
        names = _function_names(code)
        if names:
            normalized["entry_function"] = names[0]

    inputs = normalized.get("inputs")
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)
        except ValueError:
            inputs = _parse_input_assignment(inputs)
    if isinstance(inputs, str):
        parsed_input = _parse_literal(inputs)
        names = _function_argument_names(code)
        if parsed_input is not None and len(names) == 1:
            inputs = {names[0]: parsed_input}
    if isinstance(inputs, list):
        names = _function_argument_names(code)
        if len(names) == 1:
            inputs = [inputs]
        normalized["inputs"] = [
            {
                "name": names[index] if index < len(names) else f"input_{index}",
                "value": _to_tagged_json(item),
            }
            for index, item in enumerate(inputs)
        ]
    elif isinstance(inputs, dict) and "kind" not in inputs:
        normalized["inputs"] = [
            {"name": name, "value": _to_tagged_json(item)}
            for name, item in inputs.items()
        ]

    distractors = normalized.get("distractors")
    if isinstance(distractors, list):
        reasons = list(normalized.get("distractor_reasons") or [])
        converted = []
        for item in distractors:
            if isinstance(item, dict) and "distractor" in item:
                value = item["distractor"]
                reasons.append(item.get("misconception_reason", ""))
            else:
                value = item
            converted.append(_to_tagged_json(value))
        normalized["distractors"] = converted
        normalized["distractor_reasons"] = reasons[: len(converted)]
    normalized.setdefault("question_type", "mcq")
    return normalized


def _to_tagged_json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, list):
        return {
            "kind": "list",
            "scalar": None,
            "items": [_to_tagged_json(item) for item in value],
            "properties": [],
        }
    if isinstance(value, dict):
        return {
            "kind": "object",
            "scalar": None,
            "items": [],
            "properties": [
                {"key": key, "value": _to_tagged_json(item)}
                for key, item in value.items()
            ],
        }
    return {"kind": "scalar", "scalar": value, "items": [], "properties": []}


def _function_names(code: Any) -> list[str]:
    if not isinstance(code, str):
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]


def _parse_input_assignment(value: str) -> dict[str, Any] | str:
    try:
        tree = ast.parse(value, mode="exec")
        node = tree.body[0]
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            return value
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            return value
        return {target.id: ast.literal_eval(node.value)}
    except (SyntaxError, ValueError, TypeError):
        return value


def _parse_literal(value: str) -> Any:
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError, TypeError):
        return None


def build_prompt(
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
        "inputs, question, distractors, and one misconception reason for each "
        "distractor."
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
