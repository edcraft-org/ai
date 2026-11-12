"""The actual authoring response schema must expose closed problem variants."""

import pytest
from jsonschema import Draft202012Validator

from edcraft_validator.application.check_pilot.models import TemplateAuthorProposal


def test_nested_structured_family_advertises_concrete_problem_shapes():
    schema = TemplateAuthorProposal.model_json_schema()
    family = schema["$defs"]["StructuredProblemFamily"]
    problem = family["properties"]["problem"]
    variants = problem.get("anyOf", problem.get("oneOf", []))
    assert variants, (
        "The live model must see concrete problem schemas, not an empty object"
    )
    assert all("$ref" in variant or "properties" in variant for variant in variants)
    assert len(variants) >= 9


def expression_node(**fields):
    return {"num": None, "sym": None, "param": None, "op": None, "args": [], **fields}


@pytest.mark.parametrize(
    "node",
    [
        expression_node(),
        expression_node(num="1", sym="x"),
        expression_node(param="coefficient"),
        expression_node(num="1", args=[expression_node(sym="x")]),
    ],
)
def test_authoring_wire_rejects_ambiguous_or_unbound_expression_nodes(node):
    definitions = TemplateAuthorProposal.model_json_schema()["$defs"]
    validator = Draft202012Validator({"$ref": "#/$defs/Expr", "$defs": definitions})
    assert not validator.is_valid(node)


@pytest.mark.parametrize(
    "node",
    [
        expression_node(num="-3/2"),
        expression_node(sym="x"),
        expression_node(
            op="add", args=[expression_node(sym="x"), expression_node(num="1")]
        ),
    ],
)
def test_authoring_wire_accepts_closed_concrete_expression_variants(node):
    definitions = TemplateAuthorProposal.model_json_schema()["$defs"]
    validator = Draft202012Validator({"$ref": "#/$defs/Expr", "$defs": definitions})
    assert validator.is_valid(node)
