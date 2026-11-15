"""End-to-end math authoring through the generic template application."""

import pytest
from authoring_helpers import RequestPendingTools
from math_helpers import factor_ir_template, ir_proposal, quadratic_ir_template

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from tests.test_code_relevance import Decisions


def test_math_authoring_and_question_generation_round_trip() -> None:
    proposal = ir_proposal(quadratic_ir_template())
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
                        {"name": "math_verify_item_spec", "arguments": {}},
                        {"name": "math_validate_options", "arguments": {}},
                        {"name": "math_assess_template_difficulty", "arguments": {}},
                        {
                            "name": "math_verify_text_fidelity",
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
        prompt="Author a quadratic equation question with integer roots.",
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
    assert view.candidate["item"]["topic"] == "school.quadratic"
    assert view.language is None
    assert view.limits is not None
    assert view.limits["checking_mode"] == "property_based"

    assert offered == [
        "assess_template_relevance",
        "math_assess_template_difficulty",
        "math_validate_options",
        "math_verify_answer_form",
        "math_verify_item_spec",
        "math_verify_text_fidelity",
    ]
    assert validated.template.template_id.startswith("math.easy.")
    assert validated.authoring.domain == "math"
    assert validated.authoring.provider == "stub"
    assert len(validated.template.item.body.distractors) == 3
    assert validated.validation.checking_mode == "property_based"
    assert validated.validation.examples_checked == 4
    assert {item.check for item in validated.validation.evidence} == {
        "assess_template_relevance",
        "math_assess_template_difficulty",
        "math_validate_options",
        "math_verify_item_spec",
        "math_verify_text_fidelity",
    }
    assert instance.template_id == validated.template.template_id
    assert instance.artifact_id == validated.artifact_id
    assert instance.topic == "school.quadratic"
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
        "math_validate_options",
        "math_verify_answer_form",
        "math_verify_item_spec",
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


def test_math_fidelity_tool_skips_parse_back_for_symbolic_templates() -> None:
    proposal = ir_proposal(quadratic_ir_template())

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return request.response_model.model_validate(
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "checks": [
                        {"name": "math_verify_item_spec", "arguments": {}},
                        {"name": "math_validate_options", "arguments": {}},
                        {"name": "math_verify_text_fidelity", "arguments": {}},
                    ],
                }
            )

    server = create_validation_server(decision_provider_factory=Decisions)
    application = TemplateApplication(tool_client=FastMcpToolClient(server))
    result = application.author_template(
        MathTemplateRequest(
            prompt="Author a quadratic equation question with integer roots.",
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


def _author(template, selected, *, num_distractors=3):
    proposal = ir_proposal(template)

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            if request.schema_name == "template_revision":
                # Revisions return the complete proposal and no check plan.
                return proposal.model_copy(deep=True)
            return request.response_model.model_validate(
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "checks": [{"name": name, "arguments": {}} for name in selected],
                }
            )

    server = create_validation_server(decision_provider_factory=Decisions)
    application = TemplateApplication(tool_client=FastMcpToolClient(server))
    return application.author_template(
        MathTemplateRequest(
            prompt="Author a mathematics question.",
            difficulty="easy",
            num_distractors=num_distractors,
        ),
        domain=MathDomain(),
        provider=StubProvider(),
    )


def test_application_adds_the_required_checks_the_model_omits() -> None:
    result = _author(quadratic_ir_template(), ["math_assess_template_difficulty"])

    assert result.status == "checked", result.reason
    assert result.fixed_plan == [
        "math_assess_template_difficulty",
        "math_validate_options",
        "math_verify_item_spec",
    ]
    # A solve goal with symbolic text needs neither the form nor fidelity check.
    assert {item.check for item in result.artifact.validation.evidence} == set(
        result.fixed_plan
    )


def test_factor_goal_requires_the_separate_form_check() -> None:
    result = _author(factor_ir_template(), ["math_verify_item_spec"])

    assert result.status == "checked", result.reason
    assert "math_verify_answer_form" in result.fixed_plan
    form = next(
        item
        for item in result.attempts[0].executions
        if item.tool == "math_verify_answer_form"
    )
    assert form.passed


def test_correct_answer_in_the_wrong_form_fails_only_the_form_check() -> None:
    result = _author(
        factor_ir_template(factored_answer=False), ["math_verify_item_spec"]
    )

    assert result.status == "needs_review"
    executions = {item.tool: item for item in result.attempts[-1].executions}
    assert executions["math_verify_item_spec"].passed
    assert not executions["math_verify_answer_form"].passed
    assert (
        "not factored"
        in executions["math_verify_answer_form"].evidence.findings[0].message
    )


def test_too_few_distractors_requests_revision_and_blocks_the_template() -> None:
    result = _author(
        quadratic_ir_template(),
        ["math_verify_item_spec", "math_validate_options"],
        num_distractors=4,
    )

    assert result.status == "needs_review"
    assert result.artifact is None
    assert len(result.attempts) == 4
    assert result.failure.code == "TEMPLATE_CHECKS_FAILED"
    count = result.attempts[0].executions[0]
    assert count.tool == "application_distractor_count"
    assert count.evidence.findings[0].code == "TOO_FEW_DISTRACTORS"
    assert count.evidence.details == {"requested": 4, "offered": 3}


def test_fidelity_binding_keeps_authored_text_for_anchors() -> None:
    template = quadratic_ir_template()
    body = template.body
    prose_text = body.text.model_copy(
        update={
            "mode": "prose",
            "template": "Find x when {equation}. Use {p}.",
            "anchors": {"{p}": (27, 30)},
        }
    )
    prose = template.model_copy(
        update={"body": body.model_copy(update={"text": prose_text})}
    )
    candidate = MathDomain().build_candidate(
        MathTemplateRequest(prompt="Quadratic.", difficulty="easy"),
        ir_proposal(prose),
    )

    bindings = MathDomain().tool_bindings(None, candidate, "math_verify_text_fidelity")

    # Anchor spans index the authored text, so that is what the item carries.
    assert bindings["item"]["text"] == prose_text.model_dump(mode="json")
    # The blind parse-back reads the substituted wording.
    assert "{p}" not in bindings["text"] and "{equation}" not in bindings["text"]
    # The mathematics is still concrete, with parameters substituted.
    assert "'param': 'p'" not in str(bindings["item"]["givens"])


def test_required_check_missing_from_the_catalogue_is_a_configuration_error() -> None:
    from edcraft_validator.mcp.catalogue import ToolCatalogueError

    planned = type("Plan", (), {"checks": []})()

    with pytest.raises(ToolCatalogueError, match="does not offer"):
        TemplateApplication._with_required_checks(
            planned, frozenset({"math_verify_item_spec"}), {}
        )
