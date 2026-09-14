from pathlib import Path

import pytest

from edcraft_validator.domains.code.templates import (
    CodeTemplateCandidate,
    TemplateValidator,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.templates.context import CodeValidationContext
from edcraft_validator.tools.python_execution import ExecutionResult


def candidate():
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


def test_code_checks_populate_canonical_answers():
    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    from edcraft_validator.domains.code.module import CodeDomain
    from edcraft_validator.validation import ValidationPipeline

    domain = CodeDomain(
        validator_factory=lambda: TemplateValidator(execution_tool=Executor())
    )
    original = candidate()
    plan = domain.prepare_validation(original)
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    assert report.accepted
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

    checks = TemplateValidator(execution_tool=Executor()).build_checks()
    execution_check = next(check for check in checks if check.name == "code_execution")
    result = execution_check.run(CodeValidationContext(candidate()))
    assert result.status == "incomplete"
    assert result.failure.code == failure_code


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


def test_finalization_preserves_checked_content_and_deterministic_questions():
    from edcraft_validator.domains.code.module import CodeDomain
    from edcraft_validator.validation.pipeline import ValidationPipeline

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    domain = CodeDomain(
        validator_factory=lambda: TemplateValidator(execution_tool=Executor())
    )
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


def test_finalization_refuses_incomplete_report():
    import pytest

    from edcraft_validator.domains.code.module import CodeDomain
    from edcraft_validator.validation.contracts import (
        ValidationFailure,
        ValidationReport,
    )

    domain = CodeDomain()
    plan = domain.prepare_validation(candidate())
    with pytest.raises(ValidationFailure):
        domain.finalize_template(plan.context, ValidationReport([], plan.policy))


def test_safety_failure_stops_before_tool_execution():
    from edcraft_validator.application import TemplateApplication
    from edcraft_validator.domains.code.module import CodeDomain
    from edcraft_validator.domains.code.templates import TemplateValidationError

    class ForbiddenExecutor:
        def execute_batch(self, *args, **kwargs):
            pytest.fail("Unsafe code reached the execution tool")

    application = TemplateApplication(
        domain_factory=lambda name: CodeDomain(
            validator_factory=lambda: TemplateValidator(
                execution_tool=ForbiddenExecutor()
            )
        )
    )
    unsafe = candidate().model_copy(update={"code": "import os\ndef f(): return 1"})
    with pytest.raises(TemplateValidationError) as error:
        application.validate_template(unsafe, domain="code")
    assert [item.check for item in error.value.evidence] == ["template_structure"]


def test_missing_rendering_check_blocks_finalization():
    from edcraft_validator.validation import ValidationFailure, ValidationPipeline

    class Executor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=x["a"] + x["b"] - x["c"])
                for x in inputs
            ]

    from edcraft_validator.domains.code.module import CodeDomain

    domain = CodeDomain(
        validator_factory=lambda: TemplateValidator(execution_tool=Executor())
    )
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
    from edcraft_validator.domains.code.models import CodeTemplateRequest
    from edcraft_validator.domains.code.module import CodeDomain

    request = (
        None
        if num_distractors is None
        else CodeTemplateRequest(
            topic="arithmetic", difficulty="beginner", num_distractors=num_distractors
        )
    )
    plan = CodeDomain().prepare_validation(candidate(), request=request)
    assert isinstance(plan.context, CodeValidationContext)
    assert plan.context.num_distractors == num_distractors
    names = [check.name for check in plan.checks]
    assert len(names) == len(set(names))
    assert plan.policy.required_checks <= set(names)
    assert names.index("template_structure") < names.index("code_execution")
    assert names.index("expression_safety") < names.index("code_execution")
    assert names.index("canonical_answers") < names.index("distractor_selection")
