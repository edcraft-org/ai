"""Code-domain validation operations, independent of MCP transport.

Each operation owns its check sequence and result details. It returns checked
values or raises ValidationFailure; the caller handles deadlines and evidence.
"""

import copy
from typing import Any

from edcraft_validator.domains.code.checks.answer_checks import (
    check_canonical_answers,
    check_expressions,
    check_proposed_answers,
)
from edcraft_validator.domains.code.checks.distractor_checks import (
    check_distractors,
    check_proposed_distractor_selection,
)
from edcraft_validator.domains.code.checks.execution_check import ExecutionCheck
from edcraft_validator.domains.code.checks.structure_checks import (
    check_rendering,
    check_structure,
)
from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.domains.code.code_features import extract_code_features
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
)
from edcraft_validator.domains.code.code_types import CodeFeature
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.validation_contracts import ValidationFailure
from edcraft_validator.value_comparison import equivalent


def verify_template_structure(candidate: CodeTemplateCandidate) -> dict[str, Any]:
    context = CodeValidationContext(candidate)
    check_structure(context)
    check_expressions(context)
    check_proposed_answers(context)
    check_rendering(context)
    return {
        **context.case_details,
        "features": sorted(
            extract_code_features(
                context.template.code, context.template.entry_function
            )
        ),
    }


def validate_answers_and_distractors(
    candidate: CodeTemplateCandidate,
    required_distractors: int,
    *,
    execution_tool: PythonExecutionTool,
    timeout_seconds: float,
) -> dict[str, Any]:
    context = CodeValidationContext(candidate, num_distractors=required_distractors)
    check_structure(context)
    check_expressions(context)
    check_proposed_answers(context)
    ExecutionCheck(execution_tool, timeout_seconds).run(context)
    check_canonical_answers(context)

    mismatches = [
        {
            "inputs": copy.deepcopy(inputs),
            "proposed": copy.deepcopy(proposed),
            "actual": copy.deepcopy(actual),
            "trace_summary": copy.deepcopy(execution.trace_summary),
        }
        for inputs, proposed, actual, execution in zip(
            context.inputs_cases,
            context.proposed_answers,
            context.canonical_answers,
            context.executions,
            strict=True,
        )
        if not equivalent(proposed, actual)
    ]
    if mismatches:
        raise ValidationFailure(
            "The proposed answer disagrees with traced execution for "
            f"{len(mismatches)} of {len(context.inputs_cases)} cases",
            code="PROPOSED_ANSWER_MISMATCH",
            field="answer_expression",
            context={
                "cases": len(context.inputs_cases),
                "mismatches": mismatches,
            },
        )

    check_proposed_distractor_selection(context)
    check_distractors(context)
    return {
        **context.case_details,
        "canonical_answers": [
            {
                "inputs": copy.deepcopy(inputs),
                "answer": copy.deepcopy(answer),
                "trace_summary": copy.deepcopy(execution.trace_summary),
            }
            for inputs, answer, execution in zip(
                context.inputs_cases,
                context.canonical_answers,
                context.executions,
                strict=True,
            )
        ],
        "selected_distractors": [
            recipe.model_dump(mode="json") for recipe in context.template.distractors
        ],
    }


def require_features(
    candidate: CodeTemplateCandidate, required: list[CodeFeature]
) -> dict[str, Any]:
    context = CodeValidationContext(candidate)
    check_structure(context)
    observed = extract_code_features(
        context.template.code, context.template.entry_function
    )
    missing = sorted(set(required) - observed)
    if missing:
        raise ValidationFailure(
            "Required code features are missing: " + ", ".join(missing),
            code="REQUIRED_FEATURE_MISSING",
            field="code",
            context={
                "required": sorted(set(required)),
                "observed": sorted(observed),
                "missing": missing,
            },
        )
    return {
        "required": sorted(set(required)),
        "observed": sorted(observed),
    }
