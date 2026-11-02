"""Real application/MCP execution through the worker boundary, without model APIs."""

import threading

from judge_helpers import AdditionExecutor, TemplateAuthor, TemplateJudge, candidate

from edcraft_validator.application.authoring_api import (
    AuthoringJobCommand,
    AuthoringJobResponse,
    run_authoring_job,
    summarize_authoring,
)
from edcraft_validator.application.authoring_contracts import (
    AuthoringError,
    AuthoringResult,
    CheckExecution,
    DifficultyOutcome,
    GenerationAttempt,
)
from edcraft_validator.application.template_difficulty import assess_template_difficulty
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.validation.check_contracts import ToolEvidence


def command():
    return AuthoringJobCommand(
        domain="code",
        author={"provider": "scripted", "model": "author"},
        request={"prompt": "Create an addition question", "difficulty": "easy"},
    )


def application():
    return TemplateApplication(
        tool_client=FastMcpToolClient(
            create_validation_server(code_execution_tool=AdditionExecutor())
        )
    )


async def test_async_handler_runs_real_mcp_workflow_on_worker_thread():
    author = TemplateAuthor(wrong_first=True)
    progress = []
    event_loop_thread = threading.get_ident()
    job = command()
    record = await run_authoring_job(
        job,
        application_factory=application,
        provider_factory=lambda selection: author,
        on_progress=progress.append,
    )
    assert record.response.job_id == job.job_id
    assert (
        record.response.state == "completed"
        and record.response.result.status == "checked"
    )
    assert (
        record.response.result.approval == "unreviewed"
        and record.report.artifact is not None
    )
    assert (
        all(thread != event_loop_thread for thread in author.thread_ids)
        and author.closed
    )
    assert [(p.phase, p.attempt) for p in progress] == [
        ("generating", 1),
        ("checking", 1),
        ("correcting", 2),
        ("checking", 2),
        ("finalizing", 2),
    ]
    assert (
        AuthoringJobResponse.model_validate_json(record.response.model_dump_json())
        == record.response
    )


async def test_failed_observer_does_not_change_verdict():
    def observer(progress):
        raise RuntimeError("observer disconnected")

    record = await run_authoring_job(
        command(),
        application_factory=application,
        provider_factory=lambda selection: TemplateAuthor(),
        on_progress=observer,
    )
    assert record.response.result.status == "checked"


async def test_completed_job_can_need_review_without_being_approved():
    class Wrong(TemplateAuthor):
        def generate(self, request):
            self.calls = 0
            self.wrong_first = True
            return super().generate(request)

    record = await run_authoring_job(
        command(),
        application_factory=application,
        provider_factory=lambda selection: Wrong(),
    )
    assert record.response.state == "completed"
    assert record.response.result.status == "needs_review"
    assert record.response.result.approval == "unreviewed"
    assert record.response.result.artifact_id is None


async def test_factory_failure_returns_safe_typed_error():
    def broken(selection):
        raise ValueError("PRIVATE_CREDENTIAL_VALUE")

    record = await run_authoring_job(command(), provider_factory=broken)
    assert (
        record.response.state == "failed" and record.response.result.status == "error"
    )
    assert record.response.result.error.code == "CONFIGURATION_ERROR"
    assert "PRIVATE" not in record.response.model_dump_json()


def test_internal_diagnostic_exception_is_not_a_public_error_message():
    report = AuthoringResult(
        status="error",
        provider="test",
        model="test",
        domain="code",
        request={},
        prompt_version="",
        fixed_plan=[],
        tool_catalogue=[],
        failure=AuthoringError(stage="generation", code="transport"),
        reason="PRIVATE_KEY",
    )
    summary = summarize_authoring(report)
    assert (
        summary.error.code == "GENERATION_ERROR"
        and "PRIVATE" not in summary.model_dump_json()
    )


def report_with_evidence(evidence, *, status="needs_review"):
    return AuthoringResult(
        status=status,
        provider="test",
        model="test",
        domain="code",
        request={},
        prompt_version="",
        fixed_plan=[],
        tool_catalogue=[],
        attempts=[
            GenerationAttempt(
                number=1,
                candidate={},
                pending=[],
                executions=[
                    CheckExecution(
                        call_id="check",
                        tool=evidence.tool,
                        requested_arguments={},
                        evidence=evidence,
                    )
                ],
            )
        ],
    )


def test_malformed_optional_assessment_does_not_break_public_response():
    evidence = ToolEvidence(
        tool="custom_check",
        version="1",
        status="passed",
        details={"difficulty_outcome": {"PRIVATE_VALUE": "invalid"}},
    )
    summary = summarize_authoring(report_with_evidence(evidence))
    assert summary.difficulty is None and summary.error.code == "CHECK_REPORT_INVALID"
    assert "PRIVATE" not in summary.model_dump_json()


def test_unrelated_tool_outcome_is_not_a_difficulty_or_error():
    evidence = ToolEvidence(
        tool="custom_check",
        version="1",
        status="passed",
        details={"outcome": {"PRIVATE_VALUE": "invalid"}},
    )
    summary = summarize_authoring(report_with_evidence(evidence))
    assert summary.difficulty is None and summary.error is None
    assert summary.checks[0].status == "passed"
    assert "PRIVATE" not in summary.model_dump_json()


async def test_difficulty_evidence_summary_uses_the_producer_key():
    evidence = await assess_template_difficulty(
        candidate(), provider_factory=TemplateJudge
    )
    summary = summarize_authoring(report_with_evidence(evidence, status="checked"))
    assert isinstance(summary.difficulty, DifficultyOutcome)
    assert summary.difficulty.estimated_difficulty == "easy"
    assert summary.difficulty == DifficultyOutcome.model_validate(
        evidence.details["difficulty_outcome"]
    )
    assert summary.error is None
