import math
from typing import Any

import pytest

from edcraft_validator.executor import ExecutionResult
from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator


class StubExecutor:
    """Return a controlled result so validator tests do not require Docker."""

    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.calls = 0

    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        self.calls += 1
        return self.result


def successful_execution(answer: Any = 16) -> ExecutionResult:
    return ExecutionResult(
        ok=True,
        answer=answer,
        trace_summary={
            "entry_function": "square",
            "function_calls": 1,
            "loop_executions": 0,
            "branch_executions": 0,
            "variable_snapshots": 1,
        },
    )


def validator_with(result: ExecutionResult | None = None) -> QuestionValidator:
    return QuestionValidator(executor=StubExecutor(result or successful_execution()))


@pytest.mark.parametrize("timeout", [0, -1, math.inf, -math.inf, math.nan])
def test_rejects_invalid_timeout(timeout: float) -> None:
    # Validator configuration must reject zero, negative, and non-finite timeouts.
    with pytest.raises(ValueError, match="finite and greater than zero"):
        QuestionValidator(timeout_seconds=timeout)


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
    report = validator_with().validate(make_question())
    assert report.status == "valid"
    assert report.actual_answer == 16
    assert report.trace_summary is not None
    assert report.trace_summary.entry_function == "square"


def test_wrong_answer_is_rejected() -> None:
    # A manually supplied answer that differs from execution must be rejected.
    report = validator_with().validate(make_question(proposed_answer=8))
    assert report.status == "invalid"
    assert "WRONG_PROPOSED_ANSWER" in {issue.code for issue in report.issues}


def test_type_incompatible_distractor_is_rejected() -> None:
    # Distractors must have the same broad value shape as the authoritative answer.
    report = validator_with().validate(
        make_question(proposed_answer=16).model_copy(
            update={"distractors": [[1, 2], [3, 4], [5, 6]]}
        )
    )
    assert report.status == "invalid"
    assert report.issues[0].code == "DISTRACTOR_TYPE_MISMATCH"


def test_correct_distractor_is_rejected() -> None:
    # An option equal to the correct answer would make the MCQ ambiguous.
    report = validator_with().validate(make_question(distractors=[4, 16, 20]))
    assert report.status == "invalid"
    assert "DISTRACTOR_EQUALS_ANSWER" in {issue.code for issue in report.issues}


def test_duplicate_distractor_is_rejected() -> None:
    # Repeated options reduce answer quality and must be rejected.
    report = validator_with().validate(make_question(distractors=[4, 4, 20]))
    assert report.status == "invalid"
    assert "DUPLICATE_DISTRACTOR" in {issue.code for issue in report.issues}


def test_runtime_error_is_reported() -> None:
    # Runtime failures should be reported distinctly from content invalidity.
    result = ExecutionResult(
        ok=False,
        error_code="EXECUTION_FAILED",
        error_message="ZeroDivisionError: division by zero",
    )
    report = validator_with(result).validate(make_question())
    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_FAILED"


def test_timeout_is_reported() -> None:
    # Executor timeouts must propagate as execution errors.
    result = ExecutionResult(
        ok=False,
        error_code="EXECUTION_TIMEOUT",
        error_message="Execution exceeded 0.05 seconds",
    )
    report = validator_with(result).validate(make_question())
    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_TIMEOUT"


def test_unsafe_code_is_not_executed() -> None:
    # Static safety rejection must happen before Docker is started.
    executor = StubExecutor(successful_execution())
    report = QuestionValidator(executor=executor).validate(
        make_question(code="import os\ndef square(x):\n    return x")
    )
    assert report.status == "invalid"
    assert report.issues[0].code == "UNSAFE_CODE"
    assert executor.calls == 0


def test_wrong_input_name_is_reported_as_execution_error() -> None:
    # Invalid invocation inputs must not be mistaken for a valid answer.
    result = ExecutionResult(
        ok=False,
        error_code="EXECUTION_FAILED",
        error_message="TypeError: unexpected keyword argument 'value'",
    )
    report = validator_with(result).validate(make_question(inputs={"value": 4}))
    assert report.status == "execution_error"
    assert report.issues[0].code == "EXECUTION_FAILED"


def test_numeric_equivalent_distractor_is_rejected() -> None:
    # 16 and 16.0 are equivalent answers despite different numeric representations.
    report = validator_with().validate(make_question(distractors=[4, 16.0, 20]))
    assert report.status == "invalid"
    assert "DISTRACTOR_EQUALS_ANSWER" in {issue.code for issue in report.issues}


def test_question_without_function_name_is_valid_with_warning() -> None:
    # Wording uncertainty is advisory because it cannot be proven from syntax alone.
    report = validator_with().validate(
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
    report = validator_with(successful_execution(True)).validate(question)
    assert report.status == "invalid"
    assert "DISTRACTOR_TYPE_MISMATCH" in {issue.code for issue in report.issues}


def test_non_json_return_value_is_reported() -> None:
    # Sets cannot cross the JSON boundary between the worker and validator.
    question = make_question(
        code="def square(x):\n    return {x, x + 1}",
        proposed_answer=[4, 5],
    )
    result = ExecutionResult(
        ok=False,
        error_code="UNSUPPORTED_RESULT",
        error_message="The return value is not JSON-compatible",
    )
    report = validator_with(result).validate(question)
    assert report.status == "execution_error"
    assert report.issues[0].code == "UNSUPPORTED_RESULT"
