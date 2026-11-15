"""Deterministic question-expansion tests for the math domain."""

import pytest
from math_helpers import (
    checked_summary,
    ir_add,
    ir_candidate,
    ir_mul,
    ir_num,
    ir_param,
    ir_pow,
    ir_sym,
    quadratic_ir_template,
)

from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    MathTemplateSpec,
)
from edcraft_validator.domains.math.math_schemas import (
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.question_generator import (
    generate_math_question,
)
from edcraft_validator.domains.math.validation.harness import validate_template
from edcraft_validator.validation.validation_contracts import ValidationEvidence


def validated(template, artifact_id: str = "artifact-1") -> ValidatedMathTemplate:
    report = validate_template(template)
    assert report.report.status == "passed", report.report.findings
    return ValidatedMathTemplate(
        artifact_id=artifact_id,
        template=ir_candidate(template),
        validation=checked_summary(
            report,
            [
                ValidationEvidence(
                    check="math_verify_item_spec",
                    status="passed",
                )
            ],
        ),
    )


def unchecked_artifact(template) -> ValidatedMathTemplate:
    """Build an artifact that bypasses the authoring gate.

    Generation trusts an approved template, so these tests can hand it a recipe
    the authoring checks would have rejected and still see a question emitted.
    """
    return ValidatedMathTemplate(
        artifact_id="artifact-1",
        template=ir_candidate(template),
        validation=MathValidationSummary(
            examples_checked=4,
            execution_calls=4,
            max_examples=4,
            max_execution_calls=16,
            timeout_seconds=15.0,
            seed=0,
            whole_domain=True,
            declared_domain_size=4,
            evidence=[
                ValidationEvidence(check="math_verify_item_spec", status="passed")
            ],
        ),
    )


def test_same_seed_produces_an_identical_instance() -> None:
    artifact = validated(quadratic_ir_template())

    first = generate_math_question(artifact, 7)
    second = generate_math_question(artifact, 7)

    assert first == second
    assert first.artifact_id == "artifact-1"
    assert first.requires_manual_review is True


def test_different_seeds_are_reproducible() -> None:
    artifact = validated(quadratic_ir_template())

    for seed in (0, 1, 2, 42, -7):
        assert generate_math_question(artifact, seed) == generate_math_question(
            artifact, seed
        )


def test_generated_instance_has_consistent_exact_fields() -> None:
    artifact = validated(quadratic_ir_template())

    instance = generate_math_question(artifact, 3)

    assert instance.template_id == artifact.template.template_id
    assert instance.topic == "school.quadratic"
    assert set(instance.parameters) == {"p", "q"}
    assert all(type(value) is str for value in instance.parameters.values())
    assert instance.choices[instance.correct_index] == instance.answer
    assert len(instance.choices) == len(set(instance.choices)) == 4
    assert instance.question.startswith("Solve ")
    assert instance.equation in instance.question


def test_generated_answers_match_the_declared_parameter_values() -> None:
    artifact = validated(quadratic_ir_template())

    instance = generate_math_question(artifact, 0)

    # x^2 - (p + q)x + p*q = 0 has exact integer roots p and q.
    roots = instance.answer.strip("{}").replace(" ", "").split(",")
    assert {instance.parameters["p"], instance.parameters["q"]} <= set(roots)


def test_generator_refuses_distractors_that_copy_the_key() -> None:
    template = quadratic_ir_template()
    body = template.body.model_copy(
        update={
            "distractors": [
                Distractor(
                    items=[ir_param("p"), ir_param("q")],
                    misconception="COPY_KEY",
                    reason="Reports the full root set as a wrong choice.",
                )
            ]
        },
        deep=True,
    )
    artifact = unchecked_artifact(
        MathTemplateSpec(
            topic=template.topic, parameters=template.parameters, body=body
        )
    )

    with pytest.raises(ValueError, match="Could not produce"):
        generate_math_question(artifact, 0)


def test_generator_refuses_templates_without_distractors() -> None:
    template = quadratic_ir_template()
    body = template.body.model_copy(update={"distractors": []}, deep=True)
    artifact = unchecked_artifact(
        MathTemplateSpec(
            topic=template.topic, parameters=template.parameters, body=body
        )
    )

    with pytest.raises(ValueError, match="Could not produce"):
        generate_math_question(artifact, 0)


def _expand_template(recipe, *, distractors=None):
    """Build one expand family over ``k`` so the recipe can be varied."""
    from edcraft_validator.domains.math.ir.schema import (
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        SymbolSpec,
        TextSpec,
    )

    body = MathItemSpec(
        topic="school.expand",
        symbols=[SymbolSpec(name="x")],
        givens=[Given(id="domain", kind="domain", symbol="x", domain="real")],
        goal=Goal(
            kind="expand",
            expr=ir_mul(
                ir_add(ir_sym("x"), ir_param("k")), ir_add(ir_sym("x"), ir_num(2))
            ),
        ),
        answer_recipe=recipe,
        distractors=distractors
        or [
            Distractor(
                value=ir_add(ir_pow(ir_sym("x"), ir_num(2)), ir_num(2)),
                misconception="MISSING_LINEAR_TERM",
                reason="Drops the linear term",
            )
        ],
        text=TextSpec(mode="symbolic", template="Expand the product."),
    )
    return MathTemplateSpec(
        topic=body.topic,
        parameters=[ParameterSpec(name="k", values=["1"])],
        body=body,
    )


def test_generator_emits_an_expand_answer_from_the_approved_recipe():
    expanded = AnswerRecipe(
        kind="expression",
        items=[
            ir_add(
                ir_pow(ir_sym("x"), ir_num(2)),
                ir_add(
                    ir_mul(ir_add(ir_param("k"), ir_num(2)), ir_sym("x")),
                    ir_mul(ir_param("k"), ir_num(2)),
                ),
            )
        ],
    )

    instance = generate_math_question(unchecked_artifact(_expand_template(expanded)), 1)

    assert instance.answer == "x^2 + 3*x + 2"
    assert instance.choices[instance.correct_index] == instance.answer


def test_generator_emits_an_equivalent_answer_with_the_wrong_form():
    """Form is an authoring check, so generation renders the factored recipe."""
    factored = AnswerRecipe(
        kind="expression",
        items=[
            ir_mul(ir_add(ir_sym("x"), ir_param("k")), ir_add(ir_sym("x"), ir_num(2)))
        ],
    )

    instance = generate_math_question(unchecked_artifact(_expand_template(factored)), 0)

    assert instance.answer == "(x + 1)*(x + 2)"
    assert instance.choices[instance.correct_index] == instance.answer


def test_generator_emits_a_wrong_answer_recipe_without_re_grading():
    """Correctness is an authoring check, so generation renders the recipe as is."""
    wrong = AnswerRecipe(kind="set", items=[ir_add(ir_param("p"), ir_num(1000))])
    template = quadratic_ir_template()
    body = template.body.model_copy(update={"answer_recipe": wrong}, deep=True)

    instance = generate_math_question(
        unchecked_artifact(
            MathTemplateSpec(
                topic=template.topic,
                parameters=template.parameters,
                body=body,
            )
        ),
        0,
    )

    shifted = int(instance.parameters["p"]) + 1000
    assert instance.answer == f"{{{shifted}}}"
    assert instance.choices[instance.correct_index] == instance.answer
    assert instance.parameters["q"] not in instance.answer
