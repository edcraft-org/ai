"""Schema and prompt-contract tests for the math domain."""

import json

import pytest
from math_helpers import math_candidate, math_payload
from pydantic import ValidationError

from edcraft_validator.domains.domain_registry import available_domains, create_domain
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import (
    MathDistractorRecipe,
    MathParameter,
    MathQuestionInstance,
    MathTemplateCandidate,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.prompt_builder import (
    build_math_generation_request,
)
from edcraft_validator.domains.math.proposal_response import MathProposalResponse
from edcraft_validator.llm.llm_contracts import PlannedGenerationResponse
from edcraft_validator.validation.validation_contracts import ValidationEvidence


def test_request_round_trips_and_rejects_extra_fields() -> None:
    request = MathTemplateRequest(
        prompt="Make an easy linear equation question",
        difficulty="easy",
        num_distractors=3,
    )

    loaded = MathTemplateRequest.model_validate_json(request.model_dump_json())

    assert loaded == request
    with pytest.raises(ValidationError, match="Extra inputs"):
        MathTemplateRequest.model_validate(
            {
                "prompt": "A question",
                "difficulty": "easy",
                "unexpected": True,
            }
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"prompt": "   "},
        {"difficulty": "extreme"},
        {"num_distractors": 0},
        {"num_distractors": 11},
    ],
)
def test_request_rejects_invalid_values(overrides) -> None:
    payload = {
        "prompt": "A valid prompt",
        "difficulty": "easy",
        "num_distractors": 3,
        **overrides,
    }

    with pytest.raises(ValidationError):
        MathTemplateRequest.model_validate(payload)


@pytest.mark.parametrize(
    "values",
    [
        [1, 1],
        [0, 101],
        list(range(7)),
        [],
    ],
)
def test_parameter_values_are_bounded_and_unique(values) -> None:
    with pytest.raises(ValidationError):
        MathParameter(name="a", values=values)


def test_candidate_round_trips() -> None:
    candidate = math_candidate()

    loaded = MathTemplateCandidate.model_validate_json(candidate.model_dump_json())

    assert loaded == candidate
    assert loaded.template_id.startswith("math.easy.")
    assert [parameter.name for parameter in loaded.parameters] == ["a", "b", "c"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"equation_template": "2x + 3 = 7"},
        {"equation_template": "{a}x + {b} = {d}"},
        {"equation_template": "{a}x^2 + {b} = {c}"},
        {"equation_template": "{a}x - {b} = {c}"},
        {"equation_template": "{b} + {a}x = {c}"},
        {"equation_template": "{a}*x + {b} = {c}"},
        {"question_template": "Solve {unknown}: {equation}"},
        {
            "parameters": [
                {"name": "a", "values": [2]},
                {"name": "b", "values": [3]},
            ]
        },
        {
            "parameters": [
                {"name": "a", "values": [2]},
                {"name": "b", "values": [3]},
                {"name": "d", "values": [4]},
            ]
        },
        {
            "parameters": [
                {"name": "a", "values": [0, 2]},
                {"name": "b", "values": [3]},
                {"name": "c", "values": [4]},
            ]
        },
        {"distractors": []},
    ],
)
def test_candidate_rejects_malformed_or_unsupported_content(overrides) -> None:
    with pytest.raises(ValidationError):
        MathProposalResponse.model_validate(math_payload(**overrides))


def test_candidate_rejects_extra_fields() -> None:
    payload = math_payload()
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError, match="Extra inputs"):
        MathProposalResponse.model_validate(payload)


def test_distractor_recipe_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        MathDistractorRecipe(expression=" ", reason_template="Reason")


def test_validation_summary_rejects_failed_technical_evidence() -> None:
    with pytest.raises(ValidationError, match="passing validation evidence"):
        MathValidationSummary(
            combinations_checked=8,
            max_combinations=8,
            evidence=[
                ValidationEvidence(
                    check="math_verify_template_structure", status="failed"
                )
            ],
        )


def test_validated_artifact_round_trips() -> None:
    candidate = math_candidate()
    artifact = ValidatedMathTemplate(
        artifact_id="abc123",
        template=candidate,
        validation=MathValidationSummary(
            combinations_checked=8,
            max_combinations=8,
            evidence=[
                ValidationEvidence(
                    check="math_verify_template_structure", status="passed"
                ),
                ValidationEvidence(
                    check="math_validate_answers_and_distractors", status="passed"
                ),
            ],
        ),
    )

    loaded = ValidatedMathTemplate.model_validate_json(artifact.model_dump_json())

    assert loaded == artifact
    assert loaded.format_version == "1.0.0"


def test_question_instance_requires_answer_at_correct_index() -> None:
    base = {
        "template_id": "math.easy.abc",
        "seed": 1,
        "parameters": {"a": 2, "b": 2, "c": 5},
        "equation": "2x + 2 = 5",
        "question": "Solve for x: 2x + 2 = 5",
        "choices": ["3/2", "7/2"],
        "correct_index": 0,
        "answer": "3/2",
    }

    assert MathQuestionInstance.model_validate(base).answer == "3/2"
    with pytest.raises(ValidationError, match="answer must equal"):
        MathQuestionInstance.model_validate({**base, "answer": "7/2"})
    with pytest.raises(ValidationError, match="correct_index"):
        MathQuestionInstance.model_validate({**base, "correct_index": 2})
    with pytest.raises(ValidationError, match="choices must be distinct"):
        MathQuestionInstance.model_validate({**base, "choices": ["3/2", "3/2"]})


def test_generation_request_uses_math_response_contract() -> None:
    request = build_math_generation_request(
        MathTemplateRequest(
            prompt="Create an easy linear equation question",
            difficulty="easy",
            num_distractors=2,
        )
    )

    assert request.response_model == PlannedGenerationResponse[MathProposalResponse]
    assert request.check_argument_models == ()
    assert "Create an easy linear equation question" in request.messages[1]["content"]
    assert "a*x + b = c" in request.messages[0]["content"]
    assert "exact rational arithmetic" in request.messages[0]["content"]
    assert "Required usable distractors: 2" in request.messages[1]["content"]


def test_math_domain_is_registered() -> None:
    assert "math" in available_domains()
    domain = create_domain("math")
    assert isinstance(domain, MathDomain)
    assert domain.request_model is MathTemplateRequest
    assert domain.candidate_model is MathTemplateCandidate
    assert domain.validated_model is ValidatedMathTemplate
    assert domain.question_model is MathQuestionInstance


def test_generation_request_schema_is_json_serializable() -> None:
    request = build_math_generation_request(
        MathTemplateRequest(prompt="linear equations", difficulty="medium")
    )

    encoded = json.dumps(request.response_model.model_json_schema())

    assert "MathProposalResponse" in encoded
    assert "distractors" in encoded
    assert "parameters" in encoded
