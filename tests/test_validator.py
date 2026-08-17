from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator


def make_question(**changes: object) -> GeneratedQuestion:
    """Build a valid question while allowing one behavior to change per test."""
    data = {
        "code": "def square(x):\n    return x * x",
        "entry_function": "square",
        "inputs": {"x": 4},
        "question": "What value is returned by square(4)?",
        "proposed_answer": 16,
        "distractors": [4, 8, 20],
        "question_type": "mcq",
    }
    data.update(changes)
    return GeneratedQuestion.model_validate(data)


def test_valid_question() -> None:
    # This is the minimal successful schema-to-trace validation path.
    report = QuestionValidator().validate(make_question())
    assert report.status == "valid"
    assert report.actual_answer == 16
    assert report.trace_summary is not None
    assert report.trace_summary.entry_function == "square"


def test_wrong_answer_is_rejected() -> None:
    report = QuestionValidator().validate(make_question(proposed_answer=8))
    assert report.status == "invalid"
    assert "WRONG_PROPOSED_ANSWER" in {issue.code for issue in report.issues}


def test_correct_distractor_is_rejected() -> None:
    report = QuestionValidator().validate(make_question(distractors=[4, 16, 20]))
    assert report.status == "invalid"
    assert "DISTRACTOR_EQUALS_ANSWER" in {issue.code for issue in report.issues}


def test_duplicate_distractor_is_rejected() -> None:
    report = QuestionValidator().validate(make_question(distractors=[4, 4, 20]))
    assert report.status == "invalid"
    assert "DUPLICATE_DISTRACTOR" in {issue.code for issue in report.issues}


def test_runtime_error_is_reported() -> None:
    report = QuestionValidator().validate(
        make_question(code="def square(x):\n    return x / 0")
    )
    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_FAILED"


def test_timeout_is_reported() -> None:
    # A very large bounded loop reliably exceeds this intentionally short timeout.
    question = make_question(
        code=(
            "def square(x):\n"
            "    for _ in range(1000000000):\n"
            "        x += 1\n"
            "    return x"
        )
    )
    report = QuestionValidator(timeout_seconds=0.05).validate(question)
    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_TIMEOUT"


def test_unsafe_code_is_not_executed() -> None:
    # Static safety rejection must happen before the subprocess is started.
    report = QuestionValidator().validate(
        make_question(code="import os\ndef square(x):\n    return x")
    )
    assert report.status == "invalid"
    assert report.issues[0].code == "UNSAFE_CODE"


def test_wrong_input_name_is_reported_as_execution_error() -> None:
    report = QuestionValidator().validate(make_question(inputs={"value": 4}))
    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_FAILED"


def test_numeric_equivalent_distractor_is_rejected() -> None:
    # 16 and 16.0 are equivalent answers despite different numeric representations.
    report = QuestionValidator().validate(make_question(distractors=[4, 16.0, 20]))
    assert report.status == "invalid"
    assert "DISTRACTOR_EQUALS_ANSWER" in {issue.code for issue in report.issues}


def test_question_without_function_name_is_valid_with_warning() -> None:
    # Wording uncertainty is advisory because it cannot be proven from syntax alone.
    report = QuestionValidator().validate(
        make_question(question="What value is returned by the function?")
    )
    assert report.status == "valid"
    assert report.issues[0].code == "QUESTION_MAY_NOT_IDENTIFY_FUNCTION"
    assert report.issues[0].severity == "warning"


def test_boolean_answer_is_not_confused_with_integer_distractor() -> None:
    # Avoid Python's default True == 1 behavior when comparing MCQ options.
    question = make_question(
        code="def square(x):\n    return x > 0",
        proposed_answer=True,
        distractors=[1, False],
    )
    report = QuestionValidator().validate(question)
    assert report.status == "valid"


def test_non_json_return_value_is_reported() -> None:
    # Sets cannot cross the JSON boundary between the worker and validator.
    question = make_question(
        code="def square(x):\n    return {x, x + 1}",
        proposed_answer=[4, 5],
    )
    report = QuestionValidator().validate(question)
    assert report.status == "execution_error"
    assert report.issues[0].code == "UNSUPPORTED_RESULT"
