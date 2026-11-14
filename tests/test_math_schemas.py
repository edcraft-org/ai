"""Schema and prompt-contract tests for the math domain."""

import json

import pytest
from math_helpers import ir_candidate, quadratic_ir_template
from pydantic import ValidationError

from edcraft_validator.domains.domain_registry import available_domains, create_domain
from edcraft_validator.domains.math.math_domain import MathDomain
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.prompt_builder import (
    build_math_generation_request,
)
from edcraft_validator.llm.llm_contracts import PlannedGenerationResponse
from edcraft_validator.validation.validation_contracts import ValidationEvidence


def test_request_round_trips_and_rejects_extra_fields() -> None:
    request = MathTemplateRequest(
        prompt="Make an easy quadratic equation question",
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


def test_candidate_round_trips() -> None:
    candidate = ir_candidate(quadratic_ir_template())

    loaded = MathTemplateCandidate.model_validate_json(candidate.model_dump_json())

    assert loaded == candidate
    assert loaded.template_id.startswith("math.easy.")
    assert loaded.item is not None
    assert loaded.item.topic == "school.quadratic"


def test_content_requires_a_generic_item() -> None:
    with pytest.raises(ValidationError, match="item is required"):
        MathTemplateContent.model_validate({})


@pytest.mark.parametrize(
    "legacy_field",
    [
        "equation_template",
        "question_template",
        "parameters",
        "answer_expression",
        "distractors",
    ],
)
def test_content_rejects_retired_linear_fields(legacy_field) -> None:
    payload = quadratic_ir_template().model_dump(mode="json")
    payload = {"item": payload}
    payload[legacy_field] = None

    with pytest.raises(ValidationError, match="legacy linear authoring fields"):
        MathTemplateContent.model_validate(payload)


def test_content_rejects_extra_fields() -> None:
    payload = {"item": quadratic_ir_template().model_dump(mode="json")}
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError, match="Extra inputs"):
        MathTemplateContent.model_validate(payload)


def test_validation_summary_rejects_failed_technical_evidence() -> None:
    with pytest.raises(ValidationError, match="passing validation evidence"):
        MathValidationSummary(
            combinations_checked=4,
            max_combinations=4,
            evidence=[
                ValidationEvidence(check="math_verify_item_spec", status="failed")
            ],
        )


def test_validation_summary_migrates_legacy_relevance_on_read() -> None:
    summary = MathValidationSummary(
        combinations_checked=4,
        max_combinations=4,
        evidence=[
            ValidationEvidence(check="math_verify_item_spec", status="passed"),
            ValidationEvidence(check="math_validate_options", status="passed"),
            ValidationEvidence(check="math_assess_template_relevance", status="failed"),
        ],
    )

    assert summary.evidence[-1].check == "assess_template_relevance"
    assert summary.evidence[-1].status == "failed"


def test_validation_summary_drops_stale_legacy_relevance_duplicate() -> None:
    summary = MathValidationSummary(
        combinations_checked=4,
        max_combinations=4,
        evidence=[
            ValidationEvidence(check="math_verify_item_spec", status="passed"),
            ValidationEvidence(check="math_assess_template_relevance", status="failed"),
            ValidationEvidence(check="assess_template_relevance", status="failed"),
        ],
    )

    assert [item.check for item in summary.evidence] == [
        "math_verify_item_spec",
        "assess_template_relevance",
    ]


def test_validated_artifact_round_trips() -> None:
    candidate = ir_candidate(quadratic_ir_template())
    artifact = ValidatedMathTemplate(
        artifact_id="abc123",
        template=candidate,
        validation=MathValidationSummary(
            combinations_checked=4,
            max_combinations=4,
            evidence=[
                ValidationEvidence(check="math_verify_item_spec", status="passed"),
                ValidationEvidence(check="math_validate_options", status="passed"),
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
        "parameters": {"p": "2", "q": "-7"},
        "equation": "x^2 + 5*x - 14 = 0",
        "question": "Solve x^2 + 5*x - 14 = 0.",
        "choices": ["{-7, 2}", "{0}"],
        "correct_index": 0,
        "answer": "{-7, 2}",
        "topic": "school.quadratic",
    }

    assert MathQuestionInstance.model_validate(base).answer == "{-7, 2}"
    with pytest.raises(ValidationError, match="answer must equal"):
        MathQuestionInstance.model_validate({**base, "answer": "{0}"})
    with pytest.raises(ValidationError, match="correct_index"):
        MathQuestionInstance.model_validate({**base, "correct_index": 2})
    with pytest.raises(ValidationError, match="choices must be distinct"):
        MathQuestionInstance.model_validate({**base, "choices": ["{0}", "{0}"]})


def test_generation_request_uses_math_response_contract() -> None:
    request = build_math_generation_request(
        MathTemplateRequest(
            prompt="Create an easy quadratic equation question",
            difficulty="easy",
            num_distractors=2,
        )
    )

    system_prompt = request.messages[0]["content"]
    assert request.response_model == PlannedGenerationResponse[MathTemplateContent]
    assert request.check_argument_models == ()
    assert (
        "Create an easy quadratic equation question" in (request.messages[1]["content"])
    )
    assert "`item.topic`" in system_prompt
    assert "answer_recipe" in system_prompt
    assert "bounded integer literal" in system_prompt
    assert "never both" in system_prompt
    assert "different names" in system_prompt
    assert "product of factors" in system_prompt
    assert "Required usable distractors: 2" in request.messages[1]["content"]


def test_generation_request_prompt_is_ir_only() -> None:
    request = build_math_generation_request(
        MathTemplateRequest(prompt="quadratic equations", difficulty="medium")
    )
    system_prompt = request.messages[0]["content"]

    assert "equation_template" not in system_prompt
    assert "answer_expression" not in system_prompt
    assert "linear" not in system_prompt.lower()


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
        MathTemplateRequest(prompt="quadratic equations", difficulty="medium")
    )

    encoded = json.dumps(request.response_model.model_json_schema())

    assert "MathTemplateContent" in encoded
    assert "item" in encoded
    assert "parameters" in encoded


def test_proposal_response_alias_keeps_downstream_imports_working() -> None:
    from edcraft_validator.domains.math.math_schemas import MathTemplateContent
    from edcraft_validator.domains.math.proposal_response import MathProposalResponse

    assert MathProposalResponse is MathTemplateContent
