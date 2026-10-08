"""The same real author/edit/check/replay workflow for active providers."""

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateRequest,
    ValidatedCodeTemplate,
)


def check_live_workflow(provider, *, reviewed_inputs=False):
    app = TemplateApplication()
    domain = CodeDomain()
    result = app.author_template(
        CodeTemplateRequest(
            prompt=(
                "Create a Python MCQ about adding two integers. "
                "Use parameter a with values [2, 3] "
                "and parameter b with values [4, 5]. "
                "Ask for the function's return value."
            )
            if reviewed_inputs
            else "Create an arithmetic question about adding integers",
            difficulty="easy",
        ),
        domain=domain,
        provider=provider,
    )
    assert result.artifact is not None, result.model_dump_json()
    validated = result.artifact
    assert validated.validation.cases_validated >= 4
    if reviewed_inputs:
        assert {p.name: p.values for p in validated.template.parameters} == {
            "a": [2, 3],
            "b": [4, 5],
        }
    assert len(validated.template.distractors) == 3
    assert validated.template.topic is None
    assert validated.template.difficulty == "easy"
    assert validated.authoring is not None
    assert validated.authoring.provider == provider.provider
    assert validated.authoring.model

    saved = ValidatedCodeTemplate.model_validate_json(validated.model_dump_json())
    assert app.generate_question(saved, domain=domain, seed=42) == (
        app.generate_question(validated, domain=domain, seed=42)
    )

    candidate = CodeTemplateCandidate.model_validate(result.attempts[-1].candidate)
    candidate = candidate.model_copy(
        update={
            "question_template": "Consider this code. " + candidate.question_template
        }
    )
    edited = app.validate_template(candidate, domain=domain, provider=provider)
    assert edited.artifact is not None, edited.model_dump_json()
    assert edited.artifact.template.question_template == candidate.question_template
    assert edited.artifact.template.code == candidate.code
    assert (
        edited.artifact.validation.validated_cases == saved.validation.validated_cases
    )
    assert app.generate_question(
        edited.artifact, domain=domain, seed=42
    ).question.question.startswith("Consider this code. ")
