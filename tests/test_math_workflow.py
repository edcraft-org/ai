"""End-to-end math authoring through the generic template application."""

from authoring_helpers import RequestPendingTools
from math_helpers import math_proposal

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server


def test_math_authoring_and_question_generation_round_trip() -> None:
    proposal = math_proposal()
    offered = []

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            offered.extend(request.offered_tool_names)
            return request.response_model.model_validate(
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "checks": [
                        {"name": "math_verify_template_structure", "arguments": {}},
                        {
                            "name": "math_validate_answers_and_distractors",
                            "arguments": {},
                        },
                        {
                            "name": "math_assess_template_difficulty",
                            "arguments": {},
                        },
                        {
                            "name": "math_assess_template_relevance",
                            "arguments": {},
                        },
                    ],
                }
            )

    server = create_validation_server()
    application = TemplateApplication(tool_client=FastMcpToolClient(server))
    request = MathTemplateRequest(
        prompt="Solve a linear equation for x with small integer coefficients.",
        difficulty="easy",
        num_distractors=3,
    )

    validated = application.create_validated_template(
        request,
        domain=MathDomain(),
        provider=StubProvider(),
    )
    instance = application.generate_question(validated, domain=MathDomain(), seed=7)

    view = MathDomain().review_view(validated)
    assert view is not None
    assert view.template_id == validated.template.template_id
    assert view.candidate["equation_template"] == "{a}x + {b} = {c}"
    assert view.language is None
    assert view.limits is not None
    assert view.limits["checking_mode"] == "exhaustive_domain"

    assert offered == [
        "math_assess_template_difficulty",
        "math_assess_template_relevance",
        "math_validate_answers_and_distractors",
        "math_verify_template_structure",
    ]
    assert validated.template.template_id.startswith("math.easy.")
    assert validated.authoring.domain == "math"
    assert validated.authoring.provider == "stub"
    assert len(validated.template.distractors) == 3
    assert validated.validation.checking_mode == "exhaustive_domain"
    assert validated.validation.combinations_checked == 8
    assert {item.check for item in validated.validation.evidence} == {
        "math_assess_template_difficulty",
        "math_assess_template_relevance",
        "math_validate_answers_and_distractors",
        "math_verify_template_structure",
    }
    assert instance.template_id == validated.template.template_id
    assert instance.artifact_id == validated.artifact_id
    assert instance.choices[instance.correct_index] == instance.answer
    assert instance.requires_manual_review is True
    assert instance == application.generate_question(
        validated, domain=MathDomain(), seed=7
    )


def test_math_tools_are_tagged_and_listed_for_the_domain() -> None:
    with FastMcpToolClient(create_validation_server()) as client:
        tools = client.list_tools()

    math_tools = {
        tool["name"]: tool
        for tool in tools
        if "domain:math" in tool.get("_meta", {}).get("fastmcp", {}).get("tags", [])
    }

    assert set(math_tools) == {
        "math_assess_template_difficulty",
        "math_assess_template_relevance",
        "math_validate_answers_and_distractors",
        "math_verify_template_structure",
    }
    for name in (
        "math_assess_template_difficulty",
        "math_assess_template_relevance",
    ):
        tags = math_tools[name]["_meta"]["fastmcp"]["tags"]
        assert "policy:advisory" in tags
        assert "stage:after-validation" in tags
