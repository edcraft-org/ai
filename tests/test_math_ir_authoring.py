"""Generic IR authoring: validation, tools, finalization and generation."""

from __future__ import annotations

import pytest
from authoring_helpers import RequestPendingTools
from math_helpers import (
    arithmetic_ir_template,
    checked_summary,
    derivative_ir_template,
    determinant_ir_template,
    ir_candidate,
    ir_num,
    ir_param,
    ir_proposal,
    linear_ir_template,
    linear_system_ir_template,
    percentage_ir_template,
    quadratic_ir_template,
)
from pydantic import ValidationError
from test_code_relevance import Decisions

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.math.ir.instantiate import (
    declared_domain_size,
    representative_item,
)
from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Expr,
    Given,
    MathTemplateSpec,
    ParameterSpec,
    Relation,
)
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    MathTemplateContent,
    MathTemplateRequest,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import (
    MATH_IR_TOOL_VERSION,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
    MAX_DISTRACTORS,
)
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.validation.harness import validate_template
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.math_tools import (
    MathOptionsRequest,
    MathSpecRequest,
    validate_options,
    verify_item_spec,
)
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationEvidence

TEMPLATES = (
    arithmetic_ir_template,
    linear_ir_template,
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
        validation=checked_summary(
            report,
            [ValidationEvidence(check="math_verify_item_spec", status="passed")],
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


def test_linear_ir_template_is_graded_by_the_engine_and_form() -> None:
    """Linear equations are an instance of the generic IR, not a legacy path."""
    template = linear_ir_template()
    report = validate_template(template)

    assert report.report.status == "passed", report.report.findings
    assert report.examples_checked == report.declared_domain_size == 12
    engine = [
        check for check in report.report.checks if check.check == "engine_correctness"
    ]
    form = validate_template(template, aspect="form").report.checks
    assert engine and all(check.status == "passed" for check in engine)
    assert form and all(
        check.check == "form" and check.status == "passed" for check in form
    )
    assert report.report.answer.startswith("{") and report.report.answer.endswith("}")

    instance = generate_math_question(_validated(template), 0)

    assert instance.topic == "school.linear"
    assert " = " in instance.equation
    assert instance.answer.startswith("{") and instance.answer.endswith("}")
    assert instance.choices[instance.correct_index] == instance.answer


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


def test_symbolic_text_preserves_the_authored_expression() -> None:
    artifact = _validated(arithmetic_ir_template())

    instance = generate_math_question(artifact, 0)

    first, second = (int(instance.parameters[name]) for name in ("a", "b"))
    assert instance.question == f"What is {first} + {second}?"
    assert instance.equation == instance.question
    assert instance.answer == str(first + second)


def test_ir_proposal_rejects_retired_linear_fields() -> None:
    payload = ir_proposal(quadratic_ir_template()).model_dump(mode="json")
    payload["equation_template"] = "{a}x + {b} = {c}"

    with pytest.raises(ValidationError, match="legacy linear authoring fields"):
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


def test_ir_template_accepts_a_domain_far_above_the_sample_budget() -> None:
    values = [str(value) for value in range(-16, 16)]
    template = linear_ir_template()

    spec = MathTemplateSpec(
        topic=template.topic,
        parameters=[
            ParameterSpec(name=name, values=values) for name in ("a", "b", "c")
        ],
        body=template.body,
    )

    assert declared_domain_size(spec) == 32**3


def test_ir_template_accepts_more_values_per_parameter_than_the_old_sweep() -> None:
    values = [str(value) for value in range(1, 65)]
    template = linear_ir_template()

    spec = MathTemplateSpec(
        topic=template.topic,
        parameters=[
            ParameterSpec(name=name, values=values) for name in ("a", "b", "c")
        ],
        body=template.body,
    )

    assert len(spec.parameters) == 3
    assert all(len(parameter.values) == 64 for parameter in spec.parameters)


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


def test_ir_template_rejects_a_parameter_used_as_a_symbol() -> None:
    """A name cannot be both a template parameter and an item symbol."""
    template = arithmetic_ir_template()
    body = template.body.model_copy(
        update={
            "goal": template.body.goal.model_copy(
                update={"expr": Expr(op="add", args=[Expr(sym="a"), Expr(param="b")])}
            )
        },
        deep=True,
    )

    with pytest.raises(ValidationError, match="referenced as symbols"):
        MathTemplateSpec(
            topic=template.topic,
            parameters=template.parameters,
            body=body,
        )


def test_ir_template_rejects_a_parameter_that_is_never_used() -> None:
    """A declared parameter must vary the body or the learner-facing text."""
    template = arithmetic_ir_template()

    with pytest.raises(ValidationError, match="never used: c"):
        MathTemplateSpec(
            topic=template.topic,
            parameters=[
                *template.parameters,
                ParameterSpec(name="c", values=["2", "3"]),
            ],
            body=template.body,
        )


def test_representative_item_substitutes_parameters_and_text() -> None:
    template = quadratic_ir_template()

    item = representative_item(template)

    assert "{p}" not in item.text.template
    assert "{q}" not in item.text.template
    assert "x^2" in item.text.template


def test_representative_item_skips_parameter_only_guards() -> None:
    """A guard such as ``a != 0`` must not be rendered as a problem equation."""
    template = linear_ir_template()
    body = template.body.model_copy(deep=True)
    body.givens.append(
        Given(
            id="a_nonzero",
            relation=Relation(kind="ne", lhs=ir_param("a"), rhs=ir_num(0)),
        )
    )
    guarded = MathTemplateSpec(
        topic=template.topic,
        parameters=template.parameters,
        body=body,
    )

    item = representative_item(guarded)

    assert "≠" not in item.text.template
    assert item.text.template.startswith("Solve ")


def _passing_evidence(tool: str) -> ToolEvidence:
    return ToolEvidence(
        tool=tool,
        version=MATH_IR_TOOL_VERSION,
        status="passed",
        details={},
    )


def test_ir_finalization_rejects_too_many_distractors() -> None:
    template = quadratic_ir_template()
    body = template.body.model_copy(deep=True)
    body.distractors = [
        Distractor(value=Expr(num=str(index + 2)), misconception="EXTRA")
        for index in range(MAX_DISTRACTORS + 1)
    ]
    bloated = MathTemplateSpec(
        topic=template.topic,
        parameters=template.parameters,
        body=body,
    )

    # The builder trims to the requested count, so bypass it to reach the guard.
    candidate = ir_candidate(template).model_copy(update={"item": bloated})
    assert len(ir_candidate(bloated).item.body.distractors) == 3

    with pytest.raises(ValueError, match="at most"):
        MathDomain().finalize_checked_template(
            candidate,
            [
                _passing_evidence(MATH_ITEM_SPEC_TOOL),
                _passing_evidence(MATH_OPTIONS_TOOL),
            ],
            advisory_checks=frozenset(),
        )


def test_ir_tools_accept_the_finite_template() -> None:
    template = quadratic_ir_template()

    spec = verify_item_spec(MathSpecRequest(template=template))
    options = validate_options(MathOptionsRequest(template=template))

    assert spec.status == "passed"
    assert spec.details["examples_checked"] == 4
    assert options.status == "passed"


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


def test_ir_authoring_samples_a_domain_larger_than_the_budget() -> None:
    base = arithmetic_ir_template()
    values = [str(value) for value in range(1, 21)]
    template = MathTemplateSpec(
        topic=base.topic,
        parameters=[
            ParameterSpec(name="a", values=values),
            ParameterSpec(name="b", values=values),
        ],
        body=base.body,
    )
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
            prompt="Author a two-digit addition question.",
            difficulty="easy",
            num_distractors=3,
        ),
        domain=MathDomain(),
        provider=StubProvider(),
    )

    assert validated.validation.checking_mode == "property_based"
    assert 80 <= validated.validation.examples_checked <= 100
    assert validated.validation.declared_domain_size == 400

    first = application.generate_question(validated, domain=MathDomain(), seed=1)
    second = application.generate_question(validated, domain=MathDomain(), seed=2)
    assert first.choices[first.correct_index] == first.answer
    assert second.choices[second.correct_index] == second.answer


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
    assert validated.validation.examples_checked == 4

    instance = application.generate_question(validated, domain=MathDomain(), seed=1)
    assert isinstance(instance, MathQuestionInstance)
    assert instance.topic == "school.quadratic"
    assert instance.choices[instance.correct_index] == instance.answer
