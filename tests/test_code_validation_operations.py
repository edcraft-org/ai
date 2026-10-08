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
    assert verify_template_structure(candidate)["cases"] == 8
    assert require_features(candidate, ["arithmetic"])["observed"] == ["arithmetic"]

    details = validate_answers_and_distractors(
        candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
    )

    assert [case["answer"] for case in details["canonical_answers"]] == [
        6,
        4,
        9,
        7,
        8,
        6,
        11,
        9,
    ]
    assert len(details["selected_distractors"]) == 3
    # Result ownership must not expose mutable candidate state to callers.
    details["selected_distractors"][0]["expression"] = "0"
    details["canonical_answers"][0]["inputs"]["a"] = 99
    assert candidate == original


def test_checking_rejects_wrong_answers_without_repair(candidate):
    candidate.answer_expression = "a + b + c"
    with pytest.raises(ValidationFailure) as caught:
        validate_answers_and_distractors(
            candidate, 3, execution_tool=LocalPythonTool(), timeout_seconds=2
        )
    assert caught.value.code == "PROPOSED_ANSWER_MISMATCH"
    assert len(caught.value.context["mismatches"]) == 8
    assert candidate.answer_expression == "a + b + c"


@pytest.mark.parametrize("field", ["answer_expression", "distractors[0].expression"])
def test_expression_syntax_feedback_names_the_field_and_source(candidate, field):
    source = "{a} + {b}"
    if field == "answer_expression":
        candidate.answer_expression = source
    else:
        candidate.distractors[0].expression = source
    with pytest.raises(ValidationFailure) as caught:
        verify_template_structure(candidate)
    assert caught.value.field == field
    assert source in str(caught.value)
    assert "bare parameter names" in str(caught.value)
    assert "Placeholder braces belong only in text templates" in str(caught.value)


def test_checking_reports_missing_features(candidate):
    with pytest.raises(ValidationFailure) as caught:
        require_features(candidate, ["loop"])
    assert caught.value.code == "REQUIRED_FEATURE_MISSING"
    assert caught.value.context == {
        "required": ["loop"],
        "observed": ["arithmetic"],
        "missing": ["loop"],
    }
