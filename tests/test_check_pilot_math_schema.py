"""The actual authoring response schema must expose closed problem variants."""

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
