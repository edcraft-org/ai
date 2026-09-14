from pathlib import Path

from edcraft_validator.domains.code.templates import (
    CodeTemplateCandidate,
    TemplateValidator,
)
from edcraft_validator.domains.code.templates.context import CodeValidationContext
from edcraft_validator.tools.python_execution import ExecutionResult


def candidate():
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


def test_extracted_checks_match_existing_validator():
    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    validator = TemplateValidator(execution_tool=Executor())
    expected = validator.validate(candidate())
    context = CodeValidationContext(candidate())
    results = [check.run(context) for check in validator.build_checks()]
    assert all(result.status == "passed" for result in results if result is not None)
    assert context.canonical_answers == [
        case.answer for case in expected.validation.validated_cases
    ]
    assert context.template.distractors == expected.template.distractors


def test_tool_timeout_is_incomplete_and_retains_domain_error():
    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=False, error_code="EXECUTION_TIMEOUT")
                for _ in inputs
            ]

    checks = TemplateValidator(execution_tool=Executor()).build_checks()
    execution_check = next(check for check in checks if check.name == "code_execution")
    result = execution_check.run(CodeValidationContext(candidate()))
    assert result.status == "incomplete"
    assert result.failure.code == "EXECUTION_TIMEOUT"


def test_domain_supplies_plan_with_injected_tool():
    from edcraft_validator.domains.code.module import CodeDomain
    from edcraft_validator.validation.pipeline import ValidationPipeline

    calls = []

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            calls.append(inputs)
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    domain = CodeDomain(
        validator_factory=lambda: TemplateValidator(execution_tool=Executor())
    )
    plan = domain.prepare_validation(candidate())
    report = ValidationPipeline().validate(
        context=plan.context,
        checks=plan.checks,
        policy=plan.policy,
    )
    assert report.accepted
    assert len(calls) == 1
    assert "code_execution" in plan.policy.required_checks
    assert "distractor_consistency" in plan.policy.required_checks
