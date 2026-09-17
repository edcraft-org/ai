"""Checks for proposed and execution-derived template answers."""

import copy
import json
from typing import Any

from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
    DistractorCandidate,
)
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    DistractorRecipe,
    TemplateValidationError,
)
from edcraft_validator.domains.code.code_types import AnswerTarget, ParameterValue
from edcraft_validator.domains.code.profiles import code_template_profile
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.validation.validation_contracts import CheckResult
from edcraft_validator.value_comparison import equivalent


def check_expressions(context: CodeValidationContext) -> CheckResult:
    """Parse the answer and distractor expressions for later checks."""
    context.proposed_answer, context.candidates = _parse_expressions(
        context.template,
        context.names,
        allow_candidate_rejections=context.num_distractors is not None,
    )
    return CheckResult()


def check_proposed_answers(context: CodeValidationContext) -> CheckResult:
    """Evaluate the proposed answer over the complete finite input domain."""
    assert context.proposed_answer is not None
    answers = []
    for inputs in context.inputs_cases:
        answer = context.proposed_answer.evaluate(inputs)
        require_json_value(answer, "answer")
        validate_answer_kind(context.template, inputs, answer)
        answers.append(answer)
    context.proposed_answers = answers
    return CheckResult()


def check_canonical_answers(context: CodeValidationContext) -> CheckResult:
    """Derive canonical answers and preserve an incorrect proposal as a distractor."""
    answers = []
    corrected_cases = 0
    for inputs, execution, proposed_answer in zip(
        context.inputs_cases,
        context.executions,
        context.proposed_answers,
        strict=True,
    ):
        actual_answer = _execution_answer(execution, context.template.answer_target)
        require_json_value(actual_answer, "executor answer")
        validate_answer_kind(context.template, inputs, actual_answer)
        answers.append(copy.deepcopy(actual_answer))
        if not equivalent(actual_answer, proposed_answer):
            corrected_cases += 1
    context.canonical_answers = answers
    context.corrected_cases = corrected_cases
    if corrected_cases:
        assert context.proposed_answer is not None
        context.template, context.candidates = _promote_proposed_answer_to_distractor(
            context.template,
            context.proposed_answer,
            context.proposed_answers,
            context.candidates,
        )
    return CheckResult(
        details={
            "corrected_cases": corrected_cases,
            "proposal_matched": corrected_cases == 0,
        }
    )


def validate_answer_kind(
    template: CodeTemplateCandidate,
    inputs: dict[str, ParameterValue],
    answer: Any,
) -> None:
    answer_kind = code_template_profile(template.topic, template.difficulty).answer_kind
    valid = {
        "number": type(answer) in {int, float},
        "integer": type(answer) is int,
        "integer_list": type(answer) is list
        and all(type(item) is int for item in answer),
    }[answer_kind]
    if not valid:
        raise TemplateValidationError(
            f"{template.topic}/{template.difficulty} requires answer kind "
            f"{answer_kind}; received {type(answer).__name__} for inputs {inputs}",
            code="ANSWER_KIND_MISMATCH",
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


def _promote_proposed_answer_to_distractor(
    template: CodeTemplateCandidate,
    proposed_answer: SafeExpression,
    proposed_values: list[Any],
    candidates: list[DistractorCandidate],
) -> tuple[CodeTemplateCandidate, list[DistractorCandidate]]:
    if template.answer_expression is None:
        raise AssertionError("proposed answer expression is missing")

    recipes = list(template.distractors)
    existing_index = next(
        (
            index
            for index, recipe in enumerate(recipes)
            if recipe.expression == template.answer_expression
        ),
        None,
    )
    if existing_index is None:
        promoted_recipe = DistractorRecipe(
            expression=template.answer_expression,
            reason_template=(
                "Uses the original predicted answer instead of the execution result."
            ),
        )
        promoted_candidate = DistractorCandidate(
            index=0,
            expression=proposed_answer,
            values=copy.deepcopy(proposed_values),
        )
    else:
        promoted_recipe = recipes.pop(existing_index)
        candidates.pop(existing_index)
        promoted_candidate = DistractorCandidate(
            index=0,
            expression=proposed_answer,
            values=copy.deepcopy(proposed_values),
        )

    recipes.insert(0, promoted_recipe)
    candidates.insert(0, promoted_candidate)
    for index, candidate in enumerate(candidates):
        candidate.index = index
    return template.model_copy(update={"distractors": recipes}, deep=True), candidates


def _execution_answer(execution: ExecutionResult, target: AnswerTarget) -> Any:
    if target == "return_value":
        return execution.answer
    summary = execution.trace_summary
    if not isinstance(summary, dict) or target not in summary:
        raise TemplateValidationError(
            f"execution did not provide answer target {target!r}"
        )
    return summary[target]
