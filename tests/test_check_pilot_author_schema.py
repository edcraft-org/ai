"""Provider-facing strict schema compatibility for the pilot author proposals."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    PilotQualificationSettings,
    RecipeArgument,
    TemplateAuthorProposal,
)
from edcraft_validator.application.check_pilot.operations import (
    compile_recipe,
    operation_catalogue,
)
from edcraft_validator.application.check_pilot.qualification import qualify_recipe
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.openai_compatible_provider import (
    OpenAICompatibleProvider,
)


def object_shapes(value: object):
    if isinstance(value, dict):
        if value.get("type") == "object" or "properties" in value:
            yield value
        for child in value.values():
            yield from object_shapes(child)
    elif isinstance(value, list):
        for child in value:
            yield from object_shapes(child)


def defaults(value: object):
    if isinstance(value, dict):
        if "default" in value:
            yield value["default"]
        for child in value.values():
            yield from defaults(child)
    elif isinstance(value, list):
        for child in value:
            yield from defaults(child)


def assert_strict_object_shapes(schema: dict[str, object]) -> None:
    shapes = list(object_shapes(schema))
    assert shapes
    for shape in shapes:
        properties = shape.get("properties", {})
        assert shape.get("additionalProperties") is False
        assert set(shape.get("required", [])) == set(properties)
    assert not list(defaults(schema))


def argument(source: str, *, name: str | None = None, value: object = None) -> dict:
    return {"source": source, "name": name, "value": value}


def check_payload() -> dict[str, object]:
    return {
        "supported": True,
        "development_needed": None,
        "title": "Differentiate bounded polynomials",
        "description": "Compares a trusted derivative with the candidate polynomial.",
        "recipe": {
            "schema_version": "check-recipe/1",
            "operation_set": "polynomial-derivative/1",
            "steps": [
                {
                    "id": "d1",
                    "operation": "poly.differentiate",
                    "version": "1",
                    "arguments": {
                        "polynomial": argument("input", name="problem"),
                    },
                },
                {
                    "id": "out",
                    "operation": "poly.equivalent",
                    "version": "1",
                    "arguments": {
                        "expected": argument("step", name="d1"),
                        "actual": argument("input", name="candidate"),
                    },
                },
            ],
            "output": "out",
        },
    }


def template_payload() -> dict[str, object]:
    return {
        "supported": True,
        "development_needed": None,
        "family": {
            "schema_version": "polynomial-family/1",
            "variable": "x",
            "degree": 1,
            "coefficients": [
                {"exponent": 0, "values": [-2, 1, 3]},
                {"exponent": 1, "values": [-1, 1, 2]},
            ],
            "num_distractors": 3,
        },
    }


class RecordingCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.arguments: dict[str, object] | None = None

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.arguments = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=self.content, tool_calls=None),
                )
            ],
            usage=None,
        )


def provider_for(content: dict[str, object]) -> tuple[OpenAICompatibleProvider, object]:
    completions = RecordingCompletions(json.dumps(content))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatibleProvider("soclaas", client, model="test-model"), completions


@pytest.mark.parametrize("model", [CheckAuthorProposal, TemplateAuthorProposal])
def test_author_proposal_schema_is_closed_and_fully_required(model) -> None:
    schema = model.model_json_schema()

    assert_strict_object_shapes(schema)
    if model is CheckAuthorProposal:
        variants = schema["$defs"]["RecipeStep"]["anyOf"]
        operations = {
            descriptor["id"]: descriptor for descriptor in operation_catalogue()
        }
        assert {
            variant["properties"]["operation"]["const"] for variant in variants
        } == (set(operations))
        for variant in variants:
            descriptor = operations[variant["properties"]["operation"]["const"]]
            arguments = variant["properties"]["arguments"]
            assert variant["additionalProperties"] is False
            assert set(variant["required"]) == {
                "id",
                "operation",
                "version",
                "arguments",
            }
            assert arguments["type"] == "object"
            assert arguments["additionalProperties"] is False
            assert set(arguments["properties"]) == set(descriptor["inputs"])
            assert arguments["required"] == sorted(descriptor["inputs"])
            for property_schema in arguments["properties"].values():
                assert property_schema == {"$ref": "#/$defs/RecipeArgument"}
        recipe_argument = schema["$defs"]["RecipeArgument"]
        variants = recipe_argument["anyOf"]
        assert [variant["properties"]["source"]["const"] for variant in variants] == [
            "input",
            "step",
            "literal",
        ]
        for variant in variants[:2]:
            assert variant["properties"]["value"] == {"type": "null"}
            assert variant["properties"]["name"]["type"] == "string"
        literal = variants[2]
        assert literal["properties"]["name"] == {"type": "null"}
        assert literal["properties"]["value"]["anyOf"] == [
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "string"},
        ]


def test_closed_payload_with_exact_arguments_compiles_and_qualifies() -> None:
    proposal = CheckAuthorProposal.model_validate_json(json.dumps(check_payload()))

    assert isinstance(proposal, CheckAuthorProposal)
    assert proposal.recipe is not None
    assert proposal.recipe.steps[0].arguments == {
        "polynomial": RecipeArgument(source="input", name="problem")
    }
    assert proposal.recipe.steps[1].arguments == {
        "expected": RecipeArgument(source="step", name="d1"),
        "actual": RecipeArgument(source="input", name="candidate"),
    }

    compiled = compile_recipe(proposal.recipe)
    qualification = qualify_recipe(
        compiled.definition,
        seed=17,
        settings=PilotQualificationSettings(
            max_examples=20, max_execution_calls=600, timeout_seconds=30.0
        ),
    )
    assert qualification.status == "passed"
    assert qualification.counterexample is None


def test_provider_sends_closed_author_schema_and_normalizes_placeholders(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SOCLAAS_RESPONSE_FORMAT", raising=False)
    provider, completions = provider_for(check_payload())
    request = StructuredGenerationRequest(
        messages=[{"role": "user", "content": "Author a derivative check."}],
        response_model=CheckAuthorProposal,
        prompt_version="test",
        schema_name="check_author_proposal",
    )

    result = provider.generate(request)

    assert isinstance(result, CheckAuthorProposal)
    assert result.recipe is not None
    assert result.recipe.steps[0].arguments == {
        "polynomial": RecipeArgument(source="input", name="problem")
    }
    assert isinstance(result.recipe.steps[0].arguments["polynomial"], RecipeArgument)

    arguments = completions.arguments
    assert arguments is not None
    response_format = arguments["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    wire_schema = response_format["json_schema"]["schema"]
    assert wire_schema == CheckAuthorProposal.model_json_schema()
    assert_strict_object_shapes(wire_schema)
    wire_steps = wire_schema["$defs"]["RecipeStep"]["anyOf"]
    assert all(
        variant["properties"]["arguments"]["additionalProperties"] is False
        for variant in wire_steps
    )
    assert all(
        set(variant["properties"]["arguments"]["required"])
        == set(variant["properties"]["arguments"]["properties"])
        for variant in wire_steps
    )


def test_template_author_proposal_still_round_trips_through_provider(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SOCLAAS_RESPONSE_FORMAT", raising=False)
    provider, completions = provider_for(template_payload())
    request = StructuredGenerationRequest(
        messages=[{"role": "user", "content": "Author a polynomial family."}],
        response_model=TemplateAuthorProposal,
        prompt_version="test",
        schema_name="template_author_proposal",
    )

    result = provider.generate(request)

    assert isinstance(result, TemplateAuthorProposal)
    assert result.family is not None
    assert result.family.degree == 1
    assert result.family.num_distractors == 3
    assert result.family.coefficients[0].values == [-2, 1, 3]
    wire_schema = completions.arguments["response_format"]["json_schema"]["schema"]
    assert wire_schema == TemplateAuthorProposal.model_json_schema()
    assert_strict_object_shapes(wire_schema)


def test_template_author_proposal_keeps_internal_defaults() -> None:
    proposal = TemplateAuthorProposal.model_validate(
        {
            "supported": True,
            "family": {
                "degree": 1,
                "coefficients": [
                    {"exponent": 0, "values": [1]},
                    {"exponent": 1, "values": [1]},
                ],
            },
        }
    )

    assert proposal.family is not None
    assert proposal.family.schema_version == "polynomial-family/1"
    assert proposal.family.variable == "x"
    assert proposal.family.num_distractors == 3
