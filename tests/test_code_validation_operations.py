"""Exercise MCP checking operations directly, without a server or client."""

from pathlib import Path

import pytest

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.mcp.code_tools import (
    require_features,
    validate_answers_and_distractors,
    verify_template_structure,
)
from edcraft_validator.tools.python_execution import LocalPythonTool
from edcraft_validator.validation.validation_contracts import ValidationFailure


@pytest.fixture
def candidate():
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


def test_checking_operations_produce_reusable_values_without_mutating_candidate(
    candidate,
):
    original = candidate.model_copy(deep=True)
    assert 1 <= verify_template_structure(candidate)["cases"] <= 5
    assert require_features(candidate, ["arithmetic"])["observed"] == ["arithmetic"]

    details = validate_answers_and_distractors(
        candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
    )

    assert details["checking_mode"] == "property_based"
    assert details["examples_checked"] > 0
    assert len(details["selected_distractors"]) == 3
    # Result ownership must not expose mutable candidate state to callers.
    details["selected_distractors"][0]["expression"] = "0"
    assert candidate == original


def test_checking_rejects_wrong_answers_without_repair(candidate):
    candidate.answer_expression = "a + b + c"
    with pytest.raises(ValidationFailure) as caught:
        validate_answers_and_distractors(
            candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
        )
    assert caught.value.code == "PROPOSED_ANSWER_MISMATCH"
    assert caught.value.context["proposed"] != caught.value.context["actual"]
    assert caught.value.context["failing_inputs"]
    assert candidate.answer_expression == "a + b + c"


def test_answer_expression_syntax_feedback_names_the_field_and_source(candidate):
    source = "{a} + {b}"
    candidate.answer_expression = source
    with pytest.raises(ValidationFailure) as caught:
        validate_answers_and_distractors(
            candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
        )
    assert caught.value.field == "answer_expression"
    assert source in str(caught.value)
    assert "bare parameter names" in str(caught.value)
    assert "Placeholder braces belong only in text templates" in str(caught.value)


def test_invalid_distractor_expression_is_rejected_as_a_candidate(candidate):
    source = "{a} + {b}"
    candidate.distractors[0].expression = source
    with pytest.raises(ValidationFailure) as caught:
        validate_answers_and_distractors(
            candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
        )
    assert caught.value.code == "DISTRACTOR_SELECTION_FAILED"
    assert "distractors[0].expression" in str(caught.value)
    assert source in str(caught.value)
    assert "bare parameter names" in str(caught.value)


def test_answers_check_does_not_repeat_a_structure_finding(candidate):
    candidate.code = "import os\n" + candidate.code

    with pytest.raises(ValidationFailure) as structure:
        verify_template_structure(candidate)
    with pytest.raises(ValidationFailure) as answers:
        validate_answers_and_distractors(
            candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
        )

    assert structure.value.code == "UNSUPPORTED_CODE"
    assert "Import is not supported" in str(structure.value)
    assert answers.value.code == "ANSWERS_NOT_EVALUATED"
    assert answers.value.context["blocking_code"] == "UNSUPPORTED_CODE"
    assert "Import is not supported" not in str(answers.value)
    assert "structure" in str(answers.value)


@pytest.mark.parametrize("field", ["answer_expression", "distractors[0].expression"])
def test_structure_check_does_not_validate_expression_semantics(candidate, field):
    source = "{a} + {b}"
    if field == "answer_expression":
        candidate.answer_expression = source
    else:
        candidate.distractors[0].expression = source

    assert 1 <= verify_template_structure(candidate)["cases"] <= 5


def test_checking_reports_missing_features(candidate):
    with pytest.raises(ValidationFailure) as caught:
        require_features(candidate, ["loop"])
    assert caught.value.code == "REQUIRED_FEATURE_MISSING"
    assert caught.value.context == {
        "required": ["loop"],
        "observed": ["arithmetic"],
        "missing": ["loop"],
    }
