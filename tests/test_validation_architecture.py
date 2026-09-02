from typing import Any

from edcraft_validator.domains.code.pipeline import PythonValidationPipeline
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.models import GeneratedQuestion, QuestionCandidate
from edcraft_validator.validation import (
    ValidationContext,
    ValidationRun,
)


class StubExecutor:
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


def candidate(**changes: object) -> QuestionCandidate:
    data = {
        "code": "def square(x):\n    return x * x",
        "entry_function": "square",
        "inputs": {"x": 4},
        "question": "What does square(4) return?",
        "distractors": [4, 8, 20],
        "distractor_reasons": ["reason"] * 3,
    }
    data.update(changes)
    return QuestionCandidate.model_validate(data)


def successful_execution() -> ExecutionResult:
    return ExecutionResult(
        ok=True,
        answer=16,
        trace_summary={
            "entry_function": "square",
            "function_calls": 1,
            "loop_executions": 0,
            "branch_executions": 0,
            "variable_snapshots": 1,
        },
    )


def test_candidate_is_promoted_only_with_authoritative_answer() -> None:
    question = candidate().with_answer(16)

    assert isinstance(question, GeneratedQuestion)
    assert question.proposed_answer == 16
    assert question.distractor_reasons == ["reason", "reason", "reason"]


def test_python_pipeline_skips_execution_after_safety_failure() -> None:
    executor = StubExecutor(successful_execution())
    pipeline = PythonValidationPipeline(executor=executor)
    run = pipeline.compute_answer(
        ValidationContext(candidate=candidate(code="import os"))
    )

    assert run.decision == "rejected"
    assert [result.tool for result in run.results] == ["static_safety"]
    assert executor.calls == 0


def test_python_pipeline_returns_tool_evidence_and_accepts_warnings() -> None:
    pipeline = PythonValidationPipeline(executor=StubExecutor(successful_execution()))
    run = pipeline.validate(
        ValidationContext(
            candidate=candidate(question="What value is returned by the function?")
        )
    )

    assert isinstance(run, ValidationRun)
    assert run.decision == "accepted"
    assert run.actual_answer == 16
    assert [result.tool for result in run.results] == [
        "static_safety",
        "python_execution",
        "distractor_consistency",
        "question_wording",
    ]
    assert run.results[-1].issues[0].severity == "warning"
    report = run.to_report()
    assert report.status == "valid"
    assert [result["tool"] for result in report.tool_results] == [
        "static_safety",
        "python_execution",
        "distractor_consistency",
        "question_wording",
    ]
