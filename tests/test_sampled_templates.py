"""Sampled recipe contracts and independent template difficulty policy."""

import json

import pytest
from code_validation_helpers import validate_code
from pydantic import ValidationError
from test_code_templates import TrustedBatchExecutor
from test_template_difficulty import TemplateJudge, run

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    DistractorRecipe,
    TemplateValidationError,
    parse_code_template_proposal,
)
from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.proposal_response import CodeProposalResponse
from edcraft_validator.domains.code.template_difficulty import (
    build_template_difficulty_request,
    template_assessment_model,
)


def candidate():
    return CodeTemplateCandidate(
        template_id="eligible.add",
        difficulty="easy",
        code="def add(a, b):\n    return a + b",
        entry_function="add",
        parameters=[
            {"name": name, "kind": "integer", "values": [1, 2]} for name in ("a", "b")
        ],
        question_template="What does add({a}, {b}) return?",
        answer_target="return_value",
        answer_expression="a + b",
        distractors=[
            {"expression": expression, "reason_template": "A proposed misconception."}
            for expression in ("a + b - 1", "a + b + 1", "a - b")
        ],
        question_type="mcq",
    )


def test_author_schema_requires_answer_recipe_and_has_no_eligible_table():
    schema = CodeProposalResponse.model_json_schema()
    assert "answer_expression" in schema["required"]
    assert "eligible_inputs" not in schema["properties"]
    value = candidate().model_dump(
        exclude={"template_id", "topic", "difficulty", "question_type"}
    )
    proposal = CodeProposalResponse.model_validate(value)
    canonical = parse_code_template_proposal(json.dumps(proposal.model_dump()))
    assert canonical.answer_expression == "a + b"
    assert canonical.code == proposal.code
    del value["answer_expression"]
    with pytest.raises(ValidationError, match="Field required"):
        CodeProposalResponse.model_validate(value)


def test_partial_collisions_are_reported_without_an_exclusion_table():
    value = candidate()
    value.distractors[0].expression = "a * b"
    with pytest.raises(TemplateValidationError) as error:
        validate_code(value, execution_tool=TrustedBatchExecutor())
    assert error.value.code == "DISTRACTOR_SELECTION_FAILED"
    assert "eligible_inputs" not in value.model_dump()


@pytest.mark.parametrize("expression", ["a + b", "a + b if a == 1 or b == 1 else -9"])
def test_zero_or_insufficient_valid_combinations_fail(expression):
    value = candidate()
    value.distractors[0].expression = expression
    with pytest.raises(TemplateValidationError) as exc:
        validate_code(value, execution_tool=TrustedBatchExecutor())
    assert exc.value.code == "DISTRACTOR_SELECTION_FAILED"
    assert "passes all sampled cases" in str(exc.value)


def test_selection_maximizes_coverage_before_sampling():
    value = candidate()
    value.distractors.append(
        DistractorRecipe(expression="a + b - 1", reason_template="Off by one.")
    )
    value = CodeTemplateCandidate.model_validate_json(value.model_dump_json())
    validated = validate_code(value, execution_tool=TrustedBatchExecutor())
    assert "eligible_inputs" not in validated.template.model_dump()
    assert len(validated.template.distractors) == 3
    assert all(r.expression != "a * b" for r in validated.template.distractors)


@pytest.mark.parametrize(
    "eligible",
    [
        [{"a": 1, "b": 1}],
        [{"a": 1, "b": 1}, {"a": 1, "b": 1}],
        [{"a": 1, "b": 1}, {"a": 3, "b": 1}],
        [{"a": 1, "b": 1}, {"a": True, "b": 2}],
        [{"a": 1, "b": 1}, {"a": 1}],
    ],
)
def test_reloaded_domain_rejects_invalid_or_duplicate_combinations(eligible):
    with pytest.raises(ValidationError):
        CodeTemplateCandidate.model_validate(
            candidate().model_dump() | {"eligible_inputs": eligible}
        )


def test_execution_errors_are_not_hidden_by_collision_filtering():
    value = candidate().model_copy(
        update={"code": "def add(a, b):\n    return a // (b - 1)"}
    )
    with pytest.raises(TemplateValidationError, match="execution failed") as exc:
        validate_code(value, execution_tool=TrustedBatchExecutor())
    assert exc.value.field == "code"
    assert exc.value.inputs["b"] == 1


def test_judge_receives_declared_sampled_domain_and_recipe():
    value = validate_code(candidate(), execution_tool=TrustedBatchExecutor()).template
    request = build_template_difficulty_request(value, load_code_difficulty_rubric())
    payload = json.loads(request.messages[1]["content"])["template"]
    assert payload["parameters"] == [p.model_dump() for p in value.parameters]
    assert payload["answer_expression"] == "a + b"
    assert "eligible_inputs" not in payload and "difficulty" not in payload
    assert "independently and uniformly" in request.messages[0]["content"]


def test_low_confidence_mismatch_returns_warning_without_revision_or_relabelling():
    result, author, judges = run(["hard"], confidence=0.79)
    assert result.status == "checked"
    assert len(result.attempts) == len(author.generations) == len(judges) == 1
    assert result.artifact.template.difficulty == "easy"
    assert result.warnings[0].code == "DIFFICULTY_MISMATCH_LOW_CONFIDENCE"
    saved = result.artifact.validation.evidence[-1]
    assert saved.issues[0].code == result.warnings[0].code
    assert saved.details["requested_difficulty"] == "easy"
    assert saved.details["judge"]["assessment"]["estimated_difficulty"] == "hard"
    assert saved.details["decision"] == "advisory_mismatch"
    assert saved.details["confidence_calibrated"] is False


def test_high_confidence_mismatch_exhausts_three_author_revisions():
    result, author, judges = run(["hard"] * 4, confidence=0.80)
    assert result.status == "needs_review" and result.artifact is None
    assert len(result.attempts) == len(author.generations) == len(judges) == 4
    assert all(len(j.requests) == 1 for j in judges)  # Checks never repair or retry.


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_confidence_is_bounded_and_finite(confidence):
    request = build_template_difficulty_request(
        candidate(), load_code_difficulty_rubric()
    )
    value = TemplateJudge().generate(request).model_dump()
    with pytest.raises(ValidationError):
        template_assessment_model(3).model_validate(value | {"confidence": confidence})
