"""Generic IR authoring: validation, tools, finalization and generation."""

from __future__ import annotations

import pytest
from authoring_helpers import RequestPendingTools
from math_helpers import (
    derivative_ir_template,
    determinant_ir_template,
    ir_candidate,
    ir_proposal,
    linear_system_ir_template,
    percentage_ir_template,
    quadratic_ir_template,
)
from pydantic import ValidationError
from test_code_relevance import Decisions

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.math.ir.schema import (
    Expr,
    MathTemplateSpec,
    ParameterSpec,
)
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    MathTemplateContent,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.validation.harness import validate_template
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.math_tools import (
    MathOptionsRequest,
    MathSpecRequest,
    validate_answers_and_distractors,
    validate_options,
    verify_item_spec,
)
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.validation.validation_contracts import ValidationEvidence

TEMPLATES = (
    quadratic_ir_template,
    linear_system_ir_template,
    derivative_ir_template,
    determinant_ir_template,
    percentage_ir_template,
)


def _validated(template: MathTemplateSpec) -> ValidatedMathTemplate:
    report = validate_template(template)
    assert report.report.status == "passed", report.report.findings
    return ValidatedMathTemplate(
        artifact_id="artifact-ir",
        template=ir_candidate(template),
        validation=MathValidationSummary(
            combinations_checked=report.variants_checked,
            max_combinations=report.variants_total,
            evidence=[
                ValidationEvidence(check="math_verify_item_spec", status="passed")
            ],
        ),
    )


@pytest.mark.parametrize("maker", TEMPLATES)
def test_generated_ir_questions_are_reproducible_and_well_formed(maker) -> None:
    artifact = _validated(maker())

    for seed in (0, 1, 7, 42):
        first = generate_math_question(artifact, seed)
        assert first == generate_math_question(artifact, seed)
        assert first.topic == artifact.template.item.topic
        assert first.equation
        assert first.question
        assert first.choices[first.correct_index] == first.answer
        assert len(first.choices) == len(set(first.choices))
        assert first.requires_manual_review is True


def test_quadratic_generation_offers_the_derived_root_set() -> None:
    artifact = _validated(quadratic_ir_template())

    instance = generate_math_question(artifact, 1)

    assert instance.question.startswith("Solve x^2")
    assert instance.answer.startswith("{") and instance.answer.endswith("}")
    assert len(instance.parameters) == 2
    assert set(instance.parameters) == {"p", "q"}


def test_system_generation_offers_ordered_solution_tuples() -> None:
    artifact = _validated(linear_system_ir_template())

    instance = generate_math_question(artifact, 0)

    assert " and " in instance.equation
    assert instance.answer.startswith("(") and instance.answer.endswith(")")
    assert all(
        choice.startswith("(") and choice.endswith(")") for choice in instance.choices
    )


def test_derivative_generation_uses_solver_derived_expression() -> None:
    artifact = _validated(derivative_ir_template())

    instance = generate_math_question(artifact, 0)

    assert instance.equation.startswith("f(x) = ")
    assert "^" in instance.answer
    assert "**" not in instance.answer
    assert "Differentiate" in instance.question


def test_determinant_generation_offers_numeric_choices() -> None:
    artifact = _validated(determinant_ir_template())

    instance = generate_math_question(artifact, 2)

    assert instance.equation.startswith("[[")
    assert instance.answer.lstrip("-").isdigit()
    assert instance.choices[instance.correct_index] == instance.answer


def test_percentage_generation_keeps_the_authored_problem_text() -> None:
    artifact = _validated(percentage_ir_template())

    instance = generate_math_question(artifact, 2)

    assert instance.equation == instance.question
    assert "Find " in instance.question
    assert "%" in instance.question


def test_ir_proposal_rejects_mixed_authoring_modes() -> None:
    payload = ir_proposal(quadratic_ir_template()).model_dump(mode="json")
    payload["equation_template"] = "{a}x + {b} = {c}"

    with pytest.raises(ValidationError, match="not both"):
        MathTemplateContent.model_validate(payload)


def test_ir_template_rejects_undeclared_parameter_nodes() -> None:
    body = quadratic_ir_template().body
    broken = body.model_copy(
        update={"distractors": body.distractors[:1]},
        deep=True,
    )
    broken.distractors[0] = broken.distractors[0].model_copy(
        update={"value": Expr(param="z")}
    )

    with pytest.raises(ValidationError, match="undeclared parameters"):
        MathTemplateSpec(
            topic="school.quadratic",
            parameters=[ParameterSpec(name="p", values=["2"])],
            body=broken,
        )


def test_ir_template_rejects_unknown_text_placeholders() -> None:
    template = quadratic_ir_template()
    body = template.body.model_copy(
        update={
            "text": template.body.text.model_copy(update={"template": "Solve {nope}."})
        },
        deep=True,
    )

    with pytest.raises(ValidationError, match="unsupported placeholders"):
        MathTemplateSpec(
            topic=template.topic,
            parameters=template.parameters,
            body=body,
        )


def test_ir_tools_accept_the_finite_template() -> None:
    template = quadratic_ir_template()

    spec = verify_item_spec(MathSpecRequest(template=template))
    options = validate_options(MathOptionsRequest(template=template))

    assert spec.status == "passed"
    assert spec.details["variants_checked"] == 4
    assert options.status == "passed"


def test_legacy_answer_tool_rejects_a_generic_candidate() -> None:
    candidate = ir_candidate(quadratic_ir_template())

    with pytest.raises(Exception) as raised:
        validate_answers_and_distractors(candidate, 3)

    assert getattr(raised.value, "code", None) == "LEGACY_TOOL_UNAVAILABLE"


def test_math_domain_binds_ir_tools_without_model_arguments() -> None:
    domain = MathDomain()
    candidate = ir_candidate(quadratic_ir_template())
    request = MathTemplateRequest(
        prompt="Author a quadratic template.",
        difficulty="easy",
        num_distractors=3,
    )

    spec_bindings = domain.tool_bindings(request, candidate, "math_verify_item_spec")
    options_bindings = domain.tool_bindings(request, candidate, "math_validate_options")
    fidelity_bindings = domain.tool_bindings(
        request, candidate, "math_verify_text_fidelity"
    )

    assert "template" in spec_bindings
    assert "template" in options_bindings
    assert "item" in fidelity_bindings
    with pytest.raises(ValueError, match="legacy linear templates"):
        domain.tool_bindings(request, candidate, "math_verify_template_structure")


def test_ir_authoring_round_trip_through_the_application() -> None:
    template = quadratic_ir_template()
    proposal = ir_proposal(template)

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
                        {"name": "assess_template_relevance", "arguments": {}},
                    ],
                }
            )

    server = create_validation_server(decision_provider_factory=Decisions)
    application = TemplateApplication(tool_client=FastMcpToolClient(server))
    validated = application.create_validated_template(
        MathTemplateRequest(
            prompt="Author a quadratic equation question with integer roots.",
            difficulty="easy",
            num_distractors=3,
        ),
        domain=MathDomain(),
        provider=StubProvider(),
    )

    checks = {item.check: item.status for item in validated.validation.evidence}
    assert checks["math_verify_item_spec"] == "passed"
    assert checks["math_validate_options"] == "passed"
    assert checks["math_verify_text_fidelity"] == "passed"
    assert validated.validation.combinations_checked == 4

    instance = application.generate_question(validated, domain=MathDomain(), seed=1)
    assert isinstance(instance, MathQuestionInstance)
    assert instance.topic == "school.quadratic"
    assert instance.choices[instance.correct_index] == instance.answer
