from pathlib import Path

import pytest
from code_validation_helpers import validate_code

from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    ValidatedCodeTemplate,
)
from edcraft_validator.mcp.code_checks.answer_checks import check_canonical_answers
from edcraft_validator.mcp.code_checks.execution_check import ExecutionCheck
from edcraft_validator.mcp.code_checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.mcp.evidence import ToolEvidence
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.validation.validation_contracts import ValidationFailure


def candidate():
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


class ArithmeticExecutor:
    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        return [
            ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"]) for x in inputs
        ]


@pytest.mark.parametrize(
    "failure_code",
    [
        "EXECUTION_TIMEOUT",
        "TRACE_LIMIT_EXCEEDED",
        "RESOURCE_LIMIT_EXCEEDED",
        "TOOL_FAILURE",
        "INVALID_TOOL_OUTPUT",
    ],
)
def test_execution_failure_retains_domain_error(failure_code):
    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [ExecutionResult(ok=False, error_code=failure_code) for _ in inputs]

    with pytest.raises(ValidationFailure) as caught:
        ExecutionCheck(Executor()).run(CodeValidationContext(candidate()))
    assert caught.value.code == failure_code
    assert caught.value.field == "code"
    assert caught.value.inputs


def test_execution_check_uses_injected_tool_and_timeout():
    calls = []

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            calls.append((code, entry_function, inputs, timeout_seconds))
            return [ExecutionResult(ok=True, answer=0) for _ in inputs]

    context = CodeValidationContext(candidate())
    ExecutionCheck(Executor(), timeout_seconds=0.25).run(context)
    assert calls == [
        (
            context.template.code,
            context.template.entry_function,
            context.inputs_cases,
            0.25,
        )
    ]
    assert context.executions == [
        ExecutionResult(ok=True, answer=0) for _ in context.inputs_cases
    ]


def test_canonical_answer_extraction_never_promotes_or_repairs_proposals():
    context = CodeValidationContext(candidate())
    original = context.template.model_copy(deep=True)
    context.proposed_answers = [999] * len(context.inputs_cases)
    context.executions = [
        ExecutionResult(ok=True, answer=6) for _ in context.inputs_cases
    ]
    check_canonical_answers(context)
    assert context.canonical_answers == [6] * len(context.inputs_cases)
    assert context.template == original
    assert context.candidates == []


def test_finalization_preserves_checked_content_and_deterministic_questions():
    domain = CodeDomain()
    original = candidate()
    actual = validate_code(original, execution_tool=ArithmeticExecutor())
    assert actual.template == original.model_copy(update={"answer_expression": None})
    assert [case.answer for case in actual.validation.validated_cases] == [
        6,
        4,
        9,
        7,
        8,
        6,
        11,
        9,
    ]
    reloaded = ValidatedCodeTemplate.model_validate_json(actual.model_dump_json())
    assert domain.generate_question(actual, seed=42) == domain.generate_question(
        reloaded, seed=42
    )
    assert original.answer_expression is not None


@pytest.mark.parametrize("status", ["failed", "error"])
def test_finalization_rejects_unsuccessful_evidence(status):
    evidence = ToolEvidence(
        tool="code_validate_answers_and_distractors",
        version="1",
        status=status,
        findings=[{"code": "TEST_FAILURE", "message": "failed"}],
    )
    with pytest.raises(ValueError, match="All selected checks must pass"):
        CodeDomain().finalize_checked_template(candidate(), [evidence])


def test_finalization_requires_canonical_answers():
    evidence = ToolEvidence(
        tool="code_verify_template_structure", version="1", status="passed"
    )
    with pytest.raises(ValueError, match="Missing execution-derived canonical answers"):
        CodeDomain().finalize_checked_template(candidate(), [evidence])
