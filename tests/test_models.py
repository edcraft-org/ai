import pytest
from pydantic import ValidationError

from edcraft_validator.models import GeneratedQuestion


def valid_data() -> dict[str, object]:
    """Return a valid baseline that individual schema tests can modify."""
    return {
        "code": "def answer():\n    return 42",
        "entry_function": "answer",
        "inputs": {},
        "question": "What does answer() return?",
        "proposed_answer": 42,
        "distractors": [40, 44],
        "question_type": "mcq",
    }


def test_rejects_unknown_ai_fields() -> None:
    # Forbid unexpected model output instead of silently ignoring it.
    data = valid_data()
    data["confidence"] = 0.99
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GeneratedQuestion.model_validate(data)


def test_rejects_too_few_distractors() -> None:
    # An MCQ needs at least two incorrect alternatives in this first version.
    data = valid_data()
    data["distractors"] = [40]
    with pytest.raises(ValidationError, match="at least 2 items"):
        GeneratedQuestion.model_validate(data)


@pytest.mark.parametrize("field", ["code", "question"])
def test_rejects_blank_required_text(field: str) -> None:
    data = valid_data()
    data[field] = "   "
    with pytest.raises(ValidationError, match="must not be blank"):
        GeneratedQuestion.model_validate(data)


def test_rejects_invalid_entry_function_name() -> None:
    data = valid_data()
    data["entry_function"] = "not-valid"
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        GeneratedQuestion.model_validate(data)


def test_rejects_non_mcq_question_type() -> None:
    data = valid_data()
    data["question_type"] = "short_answer"
    with pytest.raises(ValidationError, match="Input should be 'mcq'"):
        GeneratedQuestion.model_validate(data)


def test_joins_readable_code_lines() -> None:
    data = valid_data()
    data["code"] = [
        "def answer():",
        "    value = 40",
        "    return value + 2",
    ]

    question = GeneratedQuestion.model_validate(data)

    assert question.code == "def answer():\n    value = 40\n    return value + 2"


def test_rejects_non_string_code_lines() -> None:
    data = valid_data()
    data["code"] = ["def answer():", 42]
    with pytest.raises(ValidationError, match="valid string"):
        GeneratedQuestion.model_validate(data)
