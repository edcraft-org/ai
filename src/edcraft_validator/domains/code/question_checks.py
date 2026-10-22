"""Python correctness and explicit requirements, independent of MCP and relevance."""

import json
from typing import Any, Literal

from pydantic import Field

from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion, Record
from edcraft_validator.domains.code.features import extract_code_features
from edcraft_validator.domains.code.relevance import CodeQuestionRequest
from edcraft_validator.tools.python_analysis import analyze_python_subset
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.value_comparison import equivalent


class TechnicalCheck(Record):
    question_sha256: str
    status: Literal["passed", "failed", "error"] = "error"
    canonical_answer: Any = None
    findings: list[str] = Field(default_factory=list)


class RequirementCheck(Record):
    question_sha256: str
    request: CodeQuestionRequest
    status: Literal["satisfied", "missing", "unknown"]
    observed_features: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    limitation: str = (
        "Checks only requested syntax in reachable functions, target and option count. "
        "Syntax presence does not prove the requested concept affects the answer. "
        "Free-text requirement coverage is not verified."
    )


def check_requirements(
    question: CodeDifficultyQuestion, request: CodeQuestionRequest
) -> RequirementCheck:
    identity = {"question_sha256": question.sha256, "request": request}
    try:
        observed = sorted(extract_code_features(question.code, question.entry_function))
    except (SyntaxError, ValueError, RecursionError):
        return RequirementCheck(
            **identity, status="unknown", findings=["FEATURES_UNAVAILABLE"]
        )
    findings = [
        f"MISSING_FEATURE:{feature}"
        for feature in sorted(set(request.required_features) - set(observed))
    ]
    if request.answer_target and question.answer_target != request.answer_target:
        findings.append("ANSWER_TARGET_MISMATCH")
    if request.num_distractors and len(question.options) - 1 != request.num_distractors:
        findings.append("DISTRACTOR_COUNT_MISMATCH")
    return RequirementCheck(
        **identity,
        status="missing" if findings else "satisfied",
        observed_features=observed,
        findings=findings,
    )


def check_concrete_correctness(
    question: CodeDifficultyQuestion,
    execution_tool: PythonExecutionTool,
    timeout_seconds: float,
) -> TechnicalCheck:
    """Derive the answer and check distinct wrong options without a model call."""
    identity = {"question_sha256": question.sha256}
    if not analyze_python_subset(question.code, question.entry_function).is_valid:
        return TechnicalCheck(
            **identity, status="failed", findings=["UNSUPPORTED_CODE"]
        )
    executions = execution_tool.execute_batch(
        question.code,
        question.entry_function,
        [question.inputs],
        timeout_seconds=timeout_seconds,
    )
    if len(executions) != 1:
        return TechnicalCheck(**identity, findings=["EXECUTOR_PROTOCOL_ERROR"])
    execution = executions[0]
    if not execution.ok:
        return TechnicalCheck(
            **identity, findings=[execution.error_code or "EXECUTION_FAILED"]
        )
    if question.answer_target == "return_value":
        answer = execution.answer
    elif (
        isinstance(execution.trace_summary, dict)
        and question.answer_target in execution.trace_summary
    ):
        answer = execution.trace_summary[question.answer_target]
    else:
        return TechnicalCheck(**identity, findings=["ANSWER_TARGET_UNAVAILABLE"])
    try:
        json.dumps(answer, allow_nan=False)
    except (TypeError, ValueError):
        return TechnicalCheck(**identity, findings=["INVALID_CANONICAL_ANSWER"])
    designated = next(
        o.value for o in question.options if o.id == question.correct_option
    )
    findings = []
    if not equivalent(designated, answer):
        findings.append("CANONICAL_ANSWER_MISMATCH")
    for index, option in enumerate(question.options):
        if option.id != question.correct_option and equivalent(option.value, answer):
            findings.append(f"DISTRACTOR_EQUALS_ANSWER:{option.id}")
        if any(equivalent(option.value, o.value) for o in question.options[:index]):
            findings.append(f"DUPLICATE_OPTION:{option.id}")
    return TechnicalCheck(
        **identity,
        status="failed" if findings else "passed",
        canonical_answer=answer,
        findings=findings,
    )
