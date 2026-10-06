"""Checks for proposed and execution-derived template answers."""

import copy
import json
from typing import Any

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    TemplateValidationError,
)
from edcraft_validator.domains.code.code_types import AnswerTarget, ParameterValue
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.mcp.code_checks.validation_context import (
    CodeValidationContext,
    DistractorCandidate,
)
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.value_comparison import same_value_shape


def check_expressions(context: CodeValidationContext) -> None:
    """Parse the answer and distractor expressions for later checks."""
    context.proposed_answer, context.candidates = _parse_expressions(
        context.template,
        context.names,
        allow_candidate_rejections=context.num_distractors is not None,
    )


def check_proposed_answers(context: CodeValidationContext) -> None:
    """Evaluate the proposed answer over the complete finite input domain."""
    assert context.proposed_answer is not None
    answers = []
    for inputs in context.inputs_cases:
        answer = context.proposed_answer.evaluate(inputs)
        require_json_value(answer, "answer")
        validate_supported_answer(inputs, answer)
        answers.append(answer)
    _require_consistent_answer_shapes(context.inputs_cases, answers)
    context.proposed_answers = answers


def check_canonical_answers(context: CodeValidationContext) -> None:
    """Derive canonical answers without changing the supplied proposal or recipes."""
    answers = []
    for inputs, execution in zip(context.inputs_cases, context.executions, strict=True):
        actual_answer = _execution_answer(execution, context.template.answer_target)
        require_json_value(actual_answer, "executor answer")
        validate_supported_answer(inputs, actual_answer)
        answers.append(copy.deepcopy(actual_answer))
    _require_consistent_answer_shapes(context.inputs_cases, answers)
    context.canonical_answers = answers


def validate_supported_answer(inputs: dict[str, ParameterValue], answer: Any) -> None:
    valid = type(answer) in {int, float, str} or (
        type(answer) is list and all(type(item) is int for item in answer)
    )
    if not valid:
        raise TemplateValidationError(
            "answers must be numbers, strings, or integer lists; "
            f"received {type(answer).__name__} for inputs {inputs}",
            code="ANSWER_TYPE_UNSUPPORTED",
            field="answer_expression",
            inputs=inputs,
        )


def _require_consistent_answer_shapes(
    inputs_cases: list[dict[str, ParameterValue]], answers: list[Any]
) -> None:
    if not answers:
        return
    expected = answers[0]
    for inputs, answer in zip(inputs_cases[1:], answers[1:], strict=True):
        if not same_value_shape(answer, expected):
            raise TemplateValidationError(
                f"answer type changes across parameter cases for inputs {inputs}",
                code="ANSWER_TYPE_INCONSISTENT",
                field="answer_expression",
                inputs=inputs,
            )


def require_json_value(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TemplateValidationError(f"{label} is not a finite JSON value") from exc


def _parse_expressions(
    template: CodeTemplateCandidate,
    names: tuple[str, ...],
    *,
    allow_candidate_rejections: bool,
) -> tuple[SafeExpression, list[DistractorCandidate]]:
    if template.answer_expression is None:
        raise TemplateValidationError(
            "template candidates require an answer_expression",
            code="ANSWER_EXPRESSION_MISSING",
            field="answer_expression",
        )
    answer = SafeExpression(template.answer_expression, names)
    candidates: list[DistractorCandidate] = []
    for index, recipe in enumerate(template.distractors):
        try:
            expression = SafeExpression(recipe.expression, names)
        except TemplateValidationError as exc:
            if not allow_candidate_rejections:
                raise
            candidates.append(DistractorCandidate(index=index, rejection=str(exc)))
        else:
            candidates.append(DistractorCandidate(index=index, expression=expression))
    return answer, candidates


def _execution_answer(execution: ExecutionResult, target: AnswerTarget) -> Any:
    if target == "return_value":
        return execution.answer
    summary = execution.trace_summary
    if not isinstance(summary, dict) or target not in summary:
        raise TemplateValidationError(
            f"execution did not provide answer target {target!r}"
        )
    return summary[target]
