"""Validation pipeline for the current Python code question domain."""

from __future__ import annotations

import time
from typing import Any

from edcraft_validator.domains.code.tools import (
    DistractorConsistencyTool,
    PythonExecutionTool,
    QuestionWordingTool,
    StaticSafetyTool,
)
from edcraft_validator.executor import DockerExecutor, ExecutionBackend
from edcraft_validator.models import GeneratedQuestion, QuestionCandidate, TraceSummary
from edcraft_validator.validation.contracts import (
    ToolResult,
    ValidationContext,
    ValidationRun,
)


class PythonValidationPipeline:
    """Compose focused tools for the existing Python MCQ workflow."""

    domain = "code"

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        executor: ExecutionBackend | None = None,
    ) -> None:
        self.static_safety = StaticSafetyTool()
        self.python_execution = PythonExecutionTool(
            executor or DockerExecutor(), timeout_seconds
        )
        self.tools = (DistractorConsistencyTool(), QuestionWordingTool())

    def compute_answer(self, context: ValidationContext) -> ValidationRun:
        safety = self._run_tool(self.static_safety, context)
        if safety.status != "passed":
            return ValidationRun(decision="rejected", results=[safety])

        execution = self._run_tool(self.python_execution, context)
        if execution.status != "passed":
            decision = "execution_error"
            return ValidationRun(decision=decision, results=[safety, execution])

        actual_answer = execution.facts.get("actual_answer")
        trace_summary = _trace_summary(execution.facts.get("trace_summary"))
        return ValidationRun(
            decision="accepted",
            results=[safety, execution],
            actual_answer=actual_answer,
            answer_available=True,
            trace_summary=trace_summary,
        )

    def validate(self, context: ValidationContext) -> ValidationRun:
        if not context.answer_available:
            answer_run = self.compute_answer(context)
            if answer_run.decision != "accepted":
                return answer_run
            context = context.model_copy(
                update={
                    "actual_answer": answer_run.actual_answer,
                    "answer_available": True,
                    "trace_summary": answer_run.trace_summary,
                }
            )
            results = answer_run.results
        else:
            results = []

        results.extend(self._run_tool(tool, context) for tool in self.tools)
        has_error = any(result.status in {"error", "timeout"} for result in results)
        has_failure = any(
            result.status == "failed"
            or any(issue.severity == "error" for issue in result.issues)
            for result in results
        )
        return ValidationRun(
            decision=(
                "execution_error"
                if has_error
                else "rejected"
                if has_failure
                else "accepted"
            ),
            results=results,
            actual_answer=context.actual_answer,
            answer_available=context.answer_available,
            trace_summary=context.trace_summary,
        )

    @staticmethod
    def _run_tool(tool: Any, context: ValidationContext) -> ToolResult:
        started = time.perf_counter()
        result = tool.validate(context)
        result.duration_ms = (time.perf_counter() - started) * 1000
        return result


def candidate_from_question(question: GeneratedQuestion) -> QuestionCandidate:
    return QuestionCandidate.from_question(question)


def _trace_summary(value: Any) -> TraceSummary | None:
    return TraceSummary.model_validate(value) if value else None
