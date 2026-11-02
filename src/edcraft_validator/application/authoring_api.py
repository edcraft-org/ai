"""Typed worker/API boundary; job lifecycle and approval are separate from checks."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from edcraft_validator.application.authoring_contracts import (
    AuthoringError,
    AuthoringProgress,
    AuthoringResult,
    DifficultyOutcome,
)
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.domain_contract import DomainModule
from edcraft_validator.domains.domain_registry import create_domain
from edcraft_validator.llm.llm_contracts import ModelProvider, TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.llm.usage import close_provider


class AuthoringJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID = Field(default_factory=uuid4)
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    author: TemplateProviderSelection
    request: dict[str, JsonValue]


class PublicAuthoringError(BaseModel):
    code: str
    message: str


class CheckSummary(BaseModel):
    tool: str
    status: Literal["passed", "failed", "error", "skipped"]
    findings: list[str] = Field(default_factory=list)


class AuthoringSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["checked", "needs_review", "error"]
    domain: str
    provider: str
    model: str
    artifact_id: str | None
    # Checking is never a human approval decision.
    approval: Literal["unreviewed"] = "unreviewed"
    difficulty: DifficultyOutcome | None = None
    checks: list[CheckSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: PublicAuthoringError | None = None


class AuthoringJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    state: Literal["queued", "running", "completed", "failed"]
    progress: AuthoringProgress | None = None
    result: AuthoringSummary | None = None


@dataclass(frozen=True)
class AuthoringJobRecord:
    """Internal persistence record. HTTP handlers return response, not report."""

    response: AuthoringJobResponse
    report: AuthoringResult


def _public_error(report: AuthoringResult) -> PublicAuthoringError | None:
    if report.failure is not None:
        messages = {
            "configuration": "Check the request and configured provider settings.",
            "generation": (
                "The model could not produce a valid response. "
                "Try again or select another model."
            ),
            "finalization": (
                "A reusable artifact could not be saved from these checks. "
                "Review the evidence."
            ),
        }
        return PublicAuthoringError(
            code=f"{report.failure.stage.upper()}_ERROR",
            message=messages.get(
                report.failure.stage,
                "Authoring stopped. Review the check results and try again.",
            ),
        )
    if not report.attempts:
        return None
    for execution in report.attempts[-1].executions:
        if execution.error or (
            execution.evidence and execution.evidence.status == "error"
        ):
            return PublicAuthoringError(
                code="CHECK_ERROR",
                message=(
                    "A check could not complete. "
                    "Verify the model or tool service and try again."
                ),
            )
    return None


def summarize_authoring(report: AuthoringResult) -> AuthoringSummary:
    checks: list[CheckSummary] = []
    difficulty: DifficultyOutcome | None = None
    invalid_outcome = False
    executions = report.attempts[-1].executions if report.attempts else []
    for execution in executions:
        evidence = execution.evidence
        checks.append(
            CheckSummary(
                tool=execution.tool,
                status=evidence.status
                if evidence
                else "error"
                if execution.error
                else "skipped",
                findings=[finding.code for finding in evidence.findings]
                if evidence
                else [],
            )
        )
        if evidence is not None and "outcome" in evidence.details:
            try:
                difficulty = DifficultyOutcome.model_validate(
                    evidence.details["outcome"]
                )
            except ValidationError:
                invalid_outcome = True
    error = _public_error(report)
    if invalid_outcome:
        error = PublicAuthoringError(
            code="CHECK_REPORT_INVALID",
            message="An assessment report could not be read. Recheck the template.",
        )
    return AuthoringSummary(
        status=report.status,
        domain=report.domain,
        provider=report.provider,
        model=report.model,
        artifact_id=report.artifact.artifact_id if report.artifact else None,
        difficulty=difficulty,
        checks=checks,
        warnings=[warning.code for warning in report.warnings],
        error=error,
    )


def run_authoring_job_sync(
    command: AuthoringJobCommand,
    *,
    application_factory: Callable[[], TemplateApplication] = TemplateApplication,
    domain_factory: Callable[[str], DomainModule] = create_domain,
    provider_factory: Callable[
        [TemplateProviderSelection], ModelProvider
    ] = create_model_provider,
    on_progress: Callable[[AuthoringProgress], None] | None = None,
) -> AuthoringJobRecord:
    """Run in a worker; preserve the complete report for evidence storage."""
    command = command.model_copy(deep=True)
    provider = None
    try:
        domain = domain_factory(command.domain)
        request = domain.request_model.model_validate(command.request)
        provider = provider_factory(command.author)
        report = application_factory().author_template(
            request, domain=domain, provider=provider, on_progress=on_progress
        )
    except Exception:
        logging.getLogger(__name__).exception("Authoring job configuration failed")
        report = AuthoringResult(
            status="error",
            provider=command.author.provider,
            model=command.author.model or "<provider-default>",
            domain=command.domain,
            request=command.request,
            prompt_version="",
            fixed_plan=[],
            tool_catalogue=[],
            failure=AuthoringError(
                stage="configuration", code="JOB_CONFIGURATION_ERROR"
            ),
        )
    finally:
        close_provider(provider)
    summary = summarize_authoring(report)
    response = AuthoringJobResponse(
        job_id=command.job_id,
        state="failed" if report.status == "error" else "completed",
        result=summary,
    )
    return AuthoringJobRecord(response=response, report=report)


async def run_authoring_job(
    command: AuthoringJobCommand,
    *,
    application_factory: Callable[[], TemplateApplication] = TemplateApplication,
    domain_factory: Callable[[str], DomainModule] = create_domain,
    provider_factory: Callable[
        [TemplateProviderSelection], ModelProvider
    ] = create_model_provider,
    on_progress: Callable[[AuthoringProgress], None] | None = None,
) -> AuthoringJobRecord:
    """Keep the synchronous MCP runner out of an HTTP handler's event loop."""
    return await asyncio.to_thread(
        run_authoring_job_sync,
        command.model_copy(deep=True),
        application_factory=application_factory,
        domain_factory=domain_factory,
        provider_factory=provider_factory,
        on_progress=on_progress,
    )
