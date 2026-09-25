from pathlib import Path

import pytest

from edcraft_validator.domains.code.checks.check_wrapper import CodeCheck
from edcraft_validator.domains.code.checks.execution_check import ExecutionCheck
from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    ValidatedCodeTemplate,
)
from edcraft_validator.tools.python_execution import ExecutionResult


def candidate():
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


def test_code_checks_populate_canonical_answers():
    calls = []

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            calls.append(inputs)
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    from edcraft_validator.domains.code.code_domain import CodeDomain
    from edcraft_validator.validation.check_runner import ValidationPipeline

    domain = CodeDomain(execution_tool=Executor())
    original = candidate()
    plan = domain.prepare_validation(original)
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    assert report.accepted
    assert calls == [plan.context.inputs_cases]
    assert plan.context.canonical_answers == [6, 4, 9, 7, 8, 6, 11, 9]
    assert plan.context.template.distractors == original.distractors


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
def test_unfinished_tool_check_is_incomplete_and_retains_domain_error(failure_code):
    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [ExecutionResult(ok=False, error_code=failure_code) for _ in inputs]

    operation = ExecutionCheck(execution_tool=Executor())
    check = CodeCheck(
        "code_execution",
        "exhaustive",
        operation.run,
        lambda context: {
            **context.case_details,
            "tool": type(operation.execution_tool).__name__,
        },
    )
    result = check.run(CodeValidationContext(candidate()))
    assert result.status == "incomplete"
    assert result.failure.code == failure_code


def test_execution_check_uses_injected_tool_and_timeout_without_validator():
    calls = []

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            calls.append((code, entry_function, inputs, timeout_seconds))
            return [ExecutionResult(ok=True, answer=0) for _ in inputs]

    context = CodeValidationContext(candidate())
    check = ExecutionCheck(execution_tool=Executor(), timeout_seconds=0.25)

    result = check.run(context)

    assert result.status == "passed"
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


def test_finalization_preserves_checked_content_and_deterministic_questions():
    from edcraft_validator.domains.code.code_domain import CodeDomain
    from edcraft_validator.validation.check_runner import ValidationPipeline

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    domain = CodeDomain(execution_tool=Executor())
    original = candidate()
    plan = domain.prepare_validation(original)
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    actual = domain.finalize_template(plan.context, report)
    assert actual.template == original.model_copy(update={"answer_expression": None})
    assert actual.validation.evidence == report.evidence
    assert [
        case.inputs for case in actual.validation.validated_cases
    ] == plan.context.inputs_cases
    assert [
        case.answer for case in actual.validation.validated_cases
    ] == plan.context.canonical_answers
    reloaded = ValidatedCodeTemplate.model_validate_json(actual.model_dump_json())
    assert domain.generate_question(actual, seed=42) == domain.generate_question(
        reloaded, seed=42
    )
    assert original.answer_expression is not None


def test_missing_rendering_check_blocks_finalization():
    from edcraft_validator.validation.check_runner import ValidationPipeline
    from edcraft_validator.validation.validation_contracts import ValidationFailure

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    from edcraft_validator.domains.code.code_domain import CodeDomain

    domain = CodeDomain(execution_tool=Executor())
    plan = domain.prepare_validation(candidate())
    report = ValidationPipeline().validate(
        context=plan.context,
        checks=[check for check in plan.checks if check.name != "template_rendering"],
        policy=plan.policy,
    )
    assert report.missing_checks == {"template_rendering"}
    with pytest.raises(ValidationFailure):
        domain.finalize_template(plan.context, report)


@pytest.mark.parametrize("num_distractors", [None, 2, 3])
def test_code_domain_plan_contract(num_distractors):
    from edcraft_validator.domains.code.code_domain import CodeDomain
    from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest

    request = (
        None
        if num_distractors is None
        else CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty="beginner",
            num_distractors=num_distractors,
        )
    )

    class UnexpectedExecutor:
        def execute_batch(self, *args, **kwargs):
            pytest.fail("Preparing a validation plan must not execute tools")

    plan = CodeDomain(execution_tool=UnexpectedExecutor()).prepare_validation(
        candidate(), request=request
    )
    assert isinstance(plan.context, CodeValidationContext)
    assert plan.context.num_distractors == num_distractors
    names = [check.name for check in plan.checks]
    assert names == [
        "template_structure",
        "expression_safety",
        "answer_domain",
        "code_execution",
        "canonical_answers",
        "distractor_selection",
        "distractor_consistency",
        "template_rendering",
    ]
    expected_required = set(names)
    if num_distractors is None:
        expected_required.remove("distractor_selection")
    assert plan.policy.required_checks == expected_required
