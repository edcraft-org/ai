"""End-to-end math authoring through the generic template application."""

from authoring_helpers import RequestPendingTools
from math_helpers import math_proposal

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from tests.test_code_relevance import Decisions


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
                            "name": "assess_template_relevance",
                            "arguments": {},
                        },
                    ],
                }
            )

    server = create_validation_server(decision_provider_factory=Decisions)
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
        "assess_template_relevance",
        "math_assess_template_difficulty",
        "math_validate_answers_and_distractors",
        "math_validate_options",
        "math_verify_item_spec",
        "math_verify_template_structure",
        "math_verify_text_fidelity",
    ]
    assert validated.template.template_id.startswith("math.easy.")
    assert validated.authoring.domain == "math"
    assert validated.authoring.provider == "stub"
    assert len(validated.template.distractors) == 3
    assert validated.validation.checking_mode == "exhaustive_domain"
    assert validated.validation.combinations_checked == 8
    assert {item.check for item in validated.validation.evidence} == {
        "assess_template_relevance",
        "math_assess_template_difficulty",
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
        "math_validate_answers_and_distractors",
        "math_validate_options",
        "math_verify_item_spec",
        "math_verify_template_structure",
        "math_verify_text_fidelity",
    }
    difficulty_tags = math_tools["math_assess_template_difficulty"]["_meta"]["fastmcp"][
        "tags"
    ]
    assert "policy:advisory" in difficulty_tags
    assert "stage:after-validation" in difficulty_tags

    relevance = next(
        tool for tool in tools if tool["name"] == "assess_template_relevance"
    )
    relevance_tags = relevance["_meta"]["fastmcp"]["tags"]
    assert "capability:template-relevance" in relevance_tags
    assert "domain:math" not in relevance_tags
    assert "policy:advisory" in relevance_tags
    assert "stage:after-validation" in relevance_tags


def test_math_authoring_executes_the_additive_ir_and_fidelity_tools() -> None:
    proposal = math_proposal()

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return request.response_model.model_validate(
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "checks": [
                        {"name": "math_verify_template_structure", "arguments": {}},
                        {
                            "name": "math_validate_answers_and_distractors",
                            "arguments": {},
                        },
                        {"name": "math_assess_template_difficulty", "arguments": {}},
                        {"name": "math_verify_item_spec", "arguments": {}},
                        {"name": "math_validate_options", "arguments": {}},
                        {"name": "math_verify_text_fidelity", "arguments": {}},
                        {"name": "assess_template_relevance", "arguments": {}},
                    ],
                }
            )

    server = create_validation_server(decision_provider_factory=Decisions)
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

    checks = {item.check: item.status for item in validated.validation.evidence}
    assert checks["math_verify_item_spec"] == "passed"
    assert checks["math_validate_options"] == "passed"
    assert checks["math_verify_text_fidelity"] == "passed"


def test_math_fidelity_tool_skips_parse_back_for_symbolic_templates() -> None:
    proposal = math_proposal()

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return request.response_model.model_validate(
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "checks": [
                        {"name": "math_verify_template_structure", "arguments": {}},
                        {
                            "name": "math_validate_answers_and_distractors",
                            "arguments": {},
                        },
                        {"name": "math_verify_text_fidelity", "arguments": {}},
                    ],
                }
            )

    server = create_validation_server(decision_provider_factory=Decisions)
    application = TemplateApplication(tool_client=FastMcpToolClient(server))
    result = application.author_template(
        MathTemplateRequest(
            prompt="Solve a linear equation for x with small integer coefficients.",
            difficulty="easy",
            num_distractors=3,
        ),
        domain=MathDomain(),
        provider=StubProvider(),
    )

    execution = next(
        execution
        for execution in result.attempts[0].executions
        if execution.tool == "math_verify_text_fidelity"
    )
    assert execution.evidence is not None
    assert execution.evidence.status == "passed"
    assert execution.evidence.details["verdict"]["reasons"] == [
        "constrained realization; no blind parse-back required"
    ]
